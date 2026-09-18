"""Standard grounding decision: the single owner of ask-vs-answer inputs.

Previously this decision was smeared over five modules: thresholds lived in
``config.yaml`` + ``config.py`` + ``assistant._FALLBACK``, scoring in
``retriever``/``scorers``, slot fills in ``slots``, and the ask-vs-answer
branching in ``assistant.answer`` (which also reached into the private
``slots._active``). This module owns the whole decision input — thresholds,
overlap, slot-grounded fallback, and the strong/weak/exact/direct assessment —
behind one interface. Callers pass retrieval candidates + turn context in and
get a plain assessment dict out. No I/O except lazy config/KB reads with the
same fallbacks as before.
"""
from __future__ import annotations

import re

from .retriever import _tokens as _tok, CONTENT_STOPWORDS
from .slots import active_slots, unfilled_slots

RESET_WORDS = ("new question", "reset", "change topic", "naya sawal", "naya prashn", "नया सवाल")
FORCE_WORDS = ("answer anyway", "assume", "just answer", "best guess")

# Defaults; live values come from config.yaml (plan §4: threshold changes need eval re-gate).
FALLBACK_THRESHOLDS = {"direct_score": 15.0, "direct_margin": 5.0, "clarify_floor": 6.0,
                       "weak_floor": 3.0, "max_rounds": 2, "max_questions_per_turn": 2}


def thresholds() -> dict:
    from .config import load as load_config
    try:
        return load_config()["retrieval"]
    except Exception:
        return dict(FALLBACK_THRESHOLDS)


def content_overlap(query: str, std: dict) -> int:
    """Shared non-stopword tokens between query and standard doc (weak-tier gate)."""
    from .scorers import doc_text
    q = _tok(query) - CONTENT_STOPWORDS
    return len(q & (_tok(doc_text(std)) - CONTENT_STOPWORDS))


def slot_grounded_iso(combined: str, stds: list[dict]) -> str | None:
    """Distinctive slot-option match for threadless chip answers (e.g. 'Single-wall').

    Accepts an IS when the query shares a distinctive option word (len>=5, used by
    <=2 standards' slots) or >=2 option words. Generic words (home/new/...) never
    ground a thread alone.
    """
    toks = _tok(combined) - CONTENT_STOPWORDS
    active = active_slots()
    per_iso: dict[str, set[str]] = {}
    df: dict[str, int] = {}
    for s in stds:
        words: set[str] = set()
        for sl in active.get(s["is_number"], []):
            for opt in sl.get("options", []):
                for w in opt.get("words", []):
                    if w.lower() in toks:
                        words.add(w.lower())
        if words:
            per_iso[s["is_number"]] = words
            for w in words:
                df[w] = df.get(w, 0) + 1
    ranked = sorted(((len(v), iso) for iso, v in per_iso.items()), reverse=True)
    for n, iso in ranked:
        if n >= 2:
            return iso
        only = next(iter(per_iso[iso]))
        if len(only) >= 5 and df.get(only, 99) <= 2:
            return iso
    return None


def assess(combined: str, cands: list[dict], ctx: dict, t: dict) -> dict:
    """Assess whether `combined` thread text grounds an answer or needs asking.

    Returns a dict with top/st/ss/exact/strong/weak/unfilled/direct. Pure move of
    the branching formerly inline in ``assistant.answer``; semantics unchanged.
    """
    from .retriever import load_kb

    top = cands[0] if cands else None
    st = top["score"] if top else 0.0
    ss = cands[1]["score"] if len(cands) > 1 else 0.0
    m = re.search(r"is\s*(\d+)", combined.lower())
    exact = bool(m and top and m.group(1) in top["std"]["is_number"])
    # Clarification only when a real phrase/IS hit grounds the thread;
    # generic token overlap (no hits) falls through to journeys/glossary.
    strong = bool(top and st >= t["clarify_floor"] and (top["hits"] or st >= t["direct_score"]))
    # Weak tier: topical (content-word) overlap earns clarification questions;
    # pure stopword overlap falls through to journeys/refusal as before.
    weak = bool(top and st >= t["weak_floor"] and content_overlap(combined, top["std"]) >= 1)
    if not weak and not strong and not exact:
        # Threadless chip answers (e.g. "Single-wall") match slot options but no
        # doc text: ground via slots so the thread continues instead of refusing.
        all_stds = load_kb()[0]
        iso = slot_grounded_iso(combined, all_stds)
        if iso:
            std = next(s for s in all_stds if s["is_number"] == iso)
            top = {"score": t["weak_floor"], "std": std, "hits": [], "confidence": "low"}
            st, ss, weak = t["weak_floor"], 0.0, True
    unfilled = unfilled_slots(top["std"]["is_number"], combined) if top else []
    direct = (exact or ctx["force"] or ctx["rounds"] >= t["max_rounds"]
              or (top and st >= t["direct_score"] and (st - ss) >= t["direct_margin"])
              or (strong and not unfilled))
    return {"top": top, "st": st, "ss": ss, "exact": exact, "strong": strong,
            "weak": weak, "unfilled": unfilled, "direct": direct}
