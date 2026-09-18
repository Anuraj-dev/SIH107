"""Common-case chat facade (Design 3): ``chat(query) -> Turn``.

Primary flow (anonymous MSME user: vague query -> 1 follow-up -> IS
candidates) is one call with strong defaults. Rare paths (export, consent,
erasure, admin KB publish) live in their existing namespaces — this module
does not absorb them.

Thin wrapper over :func:`bis_assistant.assistant.answer` + :mod:`bis_assistant.threads`:

- ``lang="auto"`` (default) defers to :func:`detect_lang`; resolved ``"en"/"hi"``
  is echoed back on every :class:`Turn`.
- ``thread=None`` or ``new_topic=True`` starts a fresh topic (drops history).
- ``force=True`` re-sends with assumptions (CLI ``assume`` / UI button).
  Material mismatches (e.g. plastic vs ``IS 17803``) still refuse by
  construction — force can never override a coverage gap.
- Server-bound handles (``id``/``token``/``expires_at``) are preserved
  across turns; local handles carry ``history``/``rounds`` opaquely.
  Callers must treat :class:`ThreadHandle` as opaque — never build
  ``{"history", "rounds", "force"}`` dicts by hand.

Legacy ``answer(q, lang, context_dict)`` is unchanged and remains the
white-box hook for tests/eval (``tests/test_assistant.py``,
``eval/run_eval.py``). New code should prefer :func:`chat`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .assistant import answer
from . import threads as threadmod

Lang = Literal["auto", "en", "hi"]
ResolvedLang = Literal["en", "hi"]

_CIT_RE = re.compile(
    r"(?P<is_number>IS\s*\d+(?:-\d+)?)\s*:?\s*(?P<year>\d{4})?"
    r".*?\[(?P<status>[^\],]+)(?:,\s*last-checked\s*(?P<last_checked>[^\]]+))?\]"
    r"\s*[—–-]\s*Source:\s*(?P<url>\S+)",
    re.IGNORECASE | re.DOTALL,
)
_IS_RE = re.compile(r"IS\s*(\d+(?:-\d+)?)", re.IGNORECASE)


@dataclass(frozen=True)
class ThreadHandle:
    """Opaque dialog handle. Do not construct ``history`` manually."""

    history: tuple[str, ...] = ()
    rounds: int = 0
    id: str | None = None  # server thread_id when bound via POST /chat
    token: str | None = None  # server owner token (X-Owner-Token)
    expires_at: str | None = None

    @staticmethod
    def fresh(
        id: str | None = None,  # noqa: A002 - matches server field name
        token: str | None = None,
        expires_at: str | None = None,
    ) -> "ThreadHandle":
        return ThreadHandle(history=(), rounds=0, id=id, token=token,
                            expires_at=expires_at)

    def to_context(self, force: bool = False) -> dict:
        return {"history": list(self.history), "rounds": int(self.rounds),
                "force": bool(force)}

    @staticmethod
    def from_context(
        ctx: dict | None,
        id: str | None = None,  # noqa: A002
        token: str | None = None,
        expires_at: str | None = None,
    ) -> "ThreadHandle":
        norm = threadmod.normalize_context(ctx)
        return ThreadHandle(history=tuple(norm["history"]),
                            rounds=int(norm["rounds"]), id=id, token=token,
                            expires_at=expires_at)


@dataclass(frozen=True)
class StructuredCitation:
    is_number: str
    year: str
    status: str
    last_checked: str
    source_url: str
    display: str


@dataclass(frozen=True)
class Turn:
    """What every caller gets back. Stable contract (see ui/src/types.ts)."""

    text: str
    lang: ResolvedLang
    kind: str
    refused: bool
    needs_info: bool
    citations: tuple[str, ...] = ()
    structured_citations: tuple[StructuredCitation, ...] = ()
    questions: tuple[dict, ...] = ()
    known: tuple[dict, ...] = ()
    assumptions: tuple[str, ...] = ()
    pii: dict = field(default_factory=dict)
    thread: ThreadHandle | None = None
    request_id: str = ""
    context: dict = field(default_factory=dict)  # legacy bridge; prefer .thread

    def to_dict(self) -> dict:
        d: dict = {
            "text": self.text,
            "refused": self.refused,
            "kind": self.kind,
            "lang": self.lang,
            "citations": list(self.citations),
            "structured_citations": [c.__dict__ for c in self.structured_citations],
            "pii": dict(self.pii),
            "needs_info": self.needs_info,
            "questions": list(self.questions),
            "known": list(self.known),
            "assumptions": list(self.assumptions),
            "context": dict(self.context),
            "request_id": self.request_id,
        }
        if self.thread is not None:
            if self.thread.id is not None:
                d["thread_id"] = self.thread.id
            if self.thread.token is not None:
                d["owner_token"] = self.thread.token
            if self.thread.expires_at is not None:
                d["expires_at"] = self.thread.expires_at
        return d


def _structure_one(display: str) -> StructuredCitation:
    m = _CIT_RE.search(display)
    if not m:
        num = _IS_RE.search(display)
        return StructuredCitation(
            is_number=f"IS {num.group(1)}" if num else "",
            year="", status="", last_checked="", source_url="", display=display)
    num = (m.group("is_number") or "").replace(" ", " ").strip()
    num = re.sub(r"\s+", " ", num)
    return StructuredCitation(
        is_number=num, year=m.group("year") or "", status=(m.group("status") or "").strip(),
        last_checked=(m.group("last_checked") or "").strip(),
        source_url=(m.group("url") or "").strip(), display=display)


def structure_citations(citations: list[str]) -> list[StructuredCitation]:
    """Parse rendered citation strings into machine-readable rows.

    Rendered form stays authoritative (``retriever.format_citation``);
    this only derives ``{is_number, year, status, last_checked, url}``
    for programmatic UIs. Unparseable rows keep ``display`` with empty fields.
    """
    return [_structure_one(c) for c in citations]


def chat(
    query: str,
    lang: Lang = "auto",
    thread: ThreadHandle | None = None,
    *,
    force: bool = False,
    new_topic: bool = False,
) -> Turn:
    """Common-case entry point: one query in, one :class:`Turn` out.

    Examples:
        t1 = chat("My startup makes water bottle. Which IS?")
        assert t1.needs_info  # <=2 questions, never a guess
        t2 = chat("stainless steel vacuum, 1 litre", thread=t1.thread)
        assert "IS 17803" in t2.text
    """
    q = (query or "").strip()
    base: ThreadHandle | None = None if (new_topic or thread is None) else thread
    lang_arg = None if lang == "auto" else lang
    ctx = (base.to_context(force=force) if base is not None
           else {"history": [], "rounds": 0, "force": bool(force)})
    resp = answer(q, lang_arg, ctx)
    resp_ctx = resp.get("context") or {"history": [], "rounds": 0}
    if base is not None and base.id is not None:
        new_handle: ThreadHandle | None = ThreadHandle(
            history=tuple(resp_ctx.get("history", [])),
            rounds=int(resp_ctx.get("rounds", 0)),
            id=base.id, token=base.token, expires_at=base.expires_at)
    else:
        new_handle = ThreadHandle(
            history=tuple(resp_ctx.get("history", [])),
            rounds=int(resp_ctx.get("rounds", 0)))
    # Design 3 policy (mirrors App.tsx): keep the handle while clarifying;
    # callers may drop it after a final answer to start fresh next turn.
    # The handle itself is always returned so CLI/tests can continue.
    struct = structure_citations(list(resp.get("citations", [])))
    return Turn(
        text=resp.get("text", ""), lang=resp.get("lang", "en"),
        kind=resp.get("kind", ""), refused=bool(resp.get("refused", False)),
        needs_info=bool(resp.get("needs_info", False)),
        citations=tuple(resp.get("citations", [])),
        structured_citations=tuple(struct),
        questions=tuple(resp.get("questions", [])),
        known=tuple(resp.get("known", [])),
        assumptions=tuple(resp.get("assumptions", [])),
        pii=dict(resp.get("pii", {})), thread=new_handle,
        context=dict(resp_ctx))


def preview_answer(
    query: str,
    lang: Lang | None = "auto",
    context: dict | None = None,
    config_override: dict | None = None,  # noqa: ARG001 - reserved for eval A/B
) -> dict:
    """Pure eval/test hook: same as :func:`answer`, no persistence.

    ``config_override`` is accepted for future threshold A/B (plan §4) and
    currently ignored — thresholds come from ``config.yaml`` (eval-gated).
    Does not bump rounds or persist anything.
    """
    lang_arg = None if lang in (None, "auto") else lang
    return answer(query or "", lang_arg, context)


__all__ = ["Lang", "ThreadHandle", "StructuredCitation", "Turn",
           "chat", "preview_answer", "structure_citations"]
