"""Dialog manager: multi-turn grounding.

Rule: never name a final standard while context is insufficient. Ask the most
discriminative questions first (max 2 per turn), merge follow-up answers into
the thread, and answer only when: exact IS match, high-confidence retrieval
with margin, all required slots filled, user forces, or 2 rounds exhausted
(then answer with stated assumptions).
"""
from __future__ import annotations
import re
from .retriever import retrieve, format_citation
from .safety import (check_never_infer, REFUSAL_EN, REFUSAL_HI,
                     DISCLAIMER_EN, DISCLAIMER_HI, BIS_CARE)
from .i18n_privacy import detect_lang, find_pii, STRINGS
from .slots import fills_for, unfilled_slots
from .grounding import (RESET_WORDS, FORCE_WORDS, FALLBACK_THRESHOLDS,
                        thresholds as _grounding_thresholds,
                        content_overlap as _grounding_overlap,
                        slot_grounded_iso as _grounding_slot_iso, assess)
from . import threads as threadmod
from . import nlu as nlu_mod
from . import memory as memory_mod

HALLMARK_HINTS = ("hallmark", "huid", "gold", "silver", "jewell", "sona", "chandi")
LAB_HINTS = ("testing", "test house", "prayogshala", "parikshan")  # "lab" matched separately
SCHEME_HINTS = ("isi", "crs", "fmcs", "licence", "license", "certification", "registration", "qco", "scheme")
CLUB_HINTS = ("club", "student", "training", "school", "college", "vidyarthi")

_LAB_WORD = re.compile(r"\blaborator(?:y|ies)\b|\blab\b", re.IGNORECASE)  # not "matlab"


def _has_lab_hint(text: str) -> bool:
    return bool(_LAB_WORD.search(text)) or any(h in text for h in LAB_HINTS)


# Materials a standard demonstrably does NOT cover (from its title/scope).
# Naming one of these downgrades recommendation -> honest coverage-gap, never a guess.
MATERIAL_EXCLUDES = {
    "IS 17803": ["plastic", "glass", "copper", "aluminium", "aluminum", "clay",
                 "silicone", "paper", "wooden", "wood"],
    "IS 694": ["rubber", "silicone"],
}


def material_mismatch(is_number: str, text: str) -> str | None:
    low = text.lower()
    for mat in MATERIAL_EXCLUDES.get(is_number, []):
        if re.search(r"\b" + re.escape(mat) + r"\b", low):
            return mat
    return None


def _content_overlap(query: str, std: dict) -> int:
    """Compat alias: owned by the grounding module."""
    return _grounding_overlap(query, std)


def _slot_grounded_iso(combined: str, stds: list[dict]) -> str | None:
    """Compat alias: owned by the grounding module."""
    return _grounding_slot_iso(combined, stds)


# Defaults; live values come from config.yaml (plan §4: threshold changes need eval re-gate).
# (RESET_WORDS/FORCE_WORDS live in the grounding module; re-exported via import above.)
_FALLBACK = dict(FALLBACK_THRESHOLDS)


def _cfg() -> dict:
    return _grounding_thresholds()


def _base(lang: str, **kw) -> dict:
    return {"text": "", "refused": False, "kind": "answered", "lang": lang,
            "citations": [], "pii": {}, "needs_info": False, "questions": [],
            "known": [], "assumptions": [], "context": {"history": [], "rounds": 0}, **kw}


# Reply-formatting helpers: every outbound text uses the same section shapes so
# the CLI, API and React console render identically —
#   - "- " bullets (never en-dashes), "1. " numbered questions,
#     "  - " indented sub-bullets (e.g. Scheme under a candidate)
#   - one blank line between sections, "---" before the footer
#   - footer is always [disclaimer?, BIS help line]; refusals/clarifications
#     carry the help line but no ruling disclaimer (nothing claimed yet).
_DIVIDER = "---"
_PORTAL = "https://www.bis.gov.in/know-your-standard"


def _disclaimer(hi: bool) -> str:
    return DISCLAIMER_HI if hi else DISCLAIMER_EN


def _footer(hi: bool, with_disclaimer: bool = True) -> list[str]:
    lines = ["", _DIVIDER]
    if with_disclaimer:
        lines.append(_disclaimer(hi))
    lines.append(BIS_CARE)
    return lines


def _rag_thresholds() -> dict:
    """Relevance gates, config-driven per issue #4 P0-2 (safe fallbacks)."""
    try:
        from .rag_config import load_rag_config
        rcfg = load_rag_config()
        return {"min_overlap": int(rcfg.get("min_overlap", 3)),
                "min_lexical": float(rcfg.get("min_lexical", 15.0)),
                "catalogue_min_score": float(rcfg.get("catalogue_min_score", 8.0))}
    except Exception:
        return {"min_overlap": 3, "min_lexical": 15.0, "catalogue_min_score": 8.0}


def _rag_relevant(text: str, evidence: list) -> bool:
    """Gate: corpus evidence must topically match, not just share tokens.

    Exact IS matches always count. Otherwise require ``min_overlap``
    content-token overlap with the top chunk (or a ``min_lexical`` score),
    so vague curated flows ("steel bottle") and chance co-occurrences
    keep their metadata behaviour while true corpus topics divert.
    Thresholds live in ``config.yaml`` (`rag:`) — see issue #4 P0-2.
    """
    if not evidence:
        return False
    top = evidence[0]
    if top.get("exact_match"):
        return True
    th = _rag_thresholds()
    import re as _re
    stop = {"what", "does", "the", "cover", "about", "which", "with", "from",
            "that", "this", "give", "summary", "scope", "standard", "indian",
            "tell", "please", "explain", "specification"}
    qtoks = {w for w in _re.findall(r"[a-z0-9]+", text.lower())
             if len(w) > 2 and w not in stop}
    if not qtoks:
        return False
    ctoks = set(_re.findall(r"[a-z0-9]+", (top.get("chunk_text") or "").lower()))
    overlap = len(qtoks & ctoks)
    # IS-number queries without exact doc match still count if digits appear
    # in the top chunk text (schedule rows quote many IS numbers).
    digits = set(_re.findall(r"\d{3,5}", text))
    chunk_digits = set(_re.findall(r"\d{3,5}", top.get("chunk_text") or ""))
    if digits and digits & chunk_digits and overlap >= 2:
        return True
    if overlap >= th["min_overlap"]:
        return True
    try:
        if float(top.get("lexical", 0.0)) >= th["min_lexical"] and overlap >= 2:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _rag_lookup(text: str, top_k: int | None = None,
                _conn=None) -> tuple[list, dict]:
    """Best-effort corpus lookup. Never raises; [] when disabled/missing."""
    try:
        from .rag_config import load_rag_config
        from .rag_retriever import search_rag
        rcfg = load_rag_config()
        if not rcfg.get("enabled"):
            return [], rcfg
        ev = search_rag(text, top_k=top_k or rcfg.get("top_k", 5),
                        db_path=rcfg.get("db_path"),
                        lexical_weight=rcfg.get("weight_lexical", 1.0),
                        semantic_weight=rcfg.get("weight_semantic", 0.3),
                        exact_boost=rcfg.get("exact_boost", 50.0),
                        semantic=rcfg.get("semantic", True),
                        embedding_model=rcfg.get("embedding_model", ""),
                        _conn=_conn)
        return ev or [], rcfg
    except Exception:
        return [], {}


class _RagConnHolder:
    """One SQLite connection per /chat turn (issue #4 P1-10).

    Lazily opened on first retrieval use, closed by ``answer()`` when the
    turn resolves. Missing DBs yield None (callers treat as no evidence).
    """

    def __init__(self) -> None:
        self.conn = None
        self.path: str | None = None

    def get(self, db_path: str | None):
        import os as _os
        if self.conn is not None:
            return self.conn
        if not db_path or not _os.path.exists(str(db_path)):
            return None
        try:
            from .rag_store import connect_rag
            self.conn = connect_rag(db_path)
            self.path = str(db_path)
            return self.conn
        except Exception:
            return None

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        finally:
            self.conn = None


def _attach_rag_sources(resp: dict, evidence: list, query_text: str = "") -> dict:
    if not evidence:
        return resp
    # Only fuse corpus sources when topically relevant; weak single-token
    # hits (e.g. "steel" alone) must not pollute curated metadata answers.
    try:
        if query_text and not _rag_relevant(query_text, evidence):
            return resp
    except Exception:
        pass
    try:
        from .rag_answer import build_sources, format_rag_citation
        resp["sources"] = build_sources(evidence)
        resp["rag_evidence"] = list(resp["sources"])
        # Union corpus citations in without rewriting curated text.
        seen = set(resp.get("citations", []))
        for e in evidence[:3]:
            c = format_rag_citation(e)
            if c not in seen:
                resp["citations"] = [*resp.get("citations", []), c]
                seen.add(c)
    except Exception:
        pass
    return resp


def _strongly_grounded(cands: list[dict], t: dict | None = None) -> bool:
    """Curated grounding robust to single generic-word collisions.

    A lone short keyword hit (e.g. query metal "iron" matching appliance
    keyword "iron") must not outrank a strong catalogue match, while phrase
    hits ("steel bottle"), multiple hits, or high scores keep priority.
    The score floor is ``retrieval.grounded_score`` (issue #4 P0-2).
    """
    floor = (t or {}).get("grounded_score", 10)
    try:
        floor = float(floor)
    except (TypeError, ValueError):
        floor = 10.0
    for c in (cands or [])[:2]:
        hits = c.get("hits") or []
        if c.get("score", 0) >= floor or len(hits) >= 2:
            return True
        if any(" " in h or len(h) > 6 for h in hits):
            return True
    return False


def _maybe_catalogue(query: str, retrieval_query: str, lang: str,
                     strong_only: bool = False, _conn=None) -> dict | None:
    """24k-catalogue fallback for novel products (RAG-gated, never raises).

    Returns a catalogue_answer only when the scan is genuinely relevant;
    gibberish and single-word probes still fall through to no_source refusal.
    With ``strong_only`` (pre-clarification path) an exact IS hit or a high
    score is required so curated questioning keeps priority on ties.
    """
    try:
        from .rag_config import load_guidance_config, load_rag_config
        rcfg = load_rag_config()
        # Independent of the corpus switch (issue #4 P0-1): only the
        # catalogue DB table must exist.
        if not load_guidance_config()["catalogue"]:
            return None
        from .catalogue_search import build_catalogue_answer, search_catalogue
        hits = search_catalogue(retrieval_query, db_path=rcfg.get("db_path"),
                                _conn=_conn)
        relevant = [h for h in hits if h.get("relevant")]
        if not relevant:
            return None
        try:
            min_score = float(rcfg.get("catalogue_min_score", 8.0))
        except (TypeError, ValueError):
            min_score = 8.0
        if strong_only and not (
                relevant[0].get("exact_match") or relevant[0].get("score", 0) >= min_score):
            return None
        return build_catalogue_answer(query, lang, relevant)
    except Exception:
        return None


def _maybe_enhance(resp: dict, query: str, intent_res: dict,
                   res: dict, lang: str) -> dict:
    """Append adaptive certification next-steps (verifier-safe, or no-op)."""
    try:
        from .rag_config import load_guidance_config
        if not load_guidance_config()["adaptive"]:
            return resp
        if resp.get("refused") or resp.get("needs_info"):
            return resp
        intent = (intent_res or {}).get("intent", "general")
        if intent not in ("certification_guidance", "process_explanation",
                          "recommend_standard"):
            return resp
        from . import guidance as guidance_mod
        hi = lang == "hi"
        schemes_info = []
        for s in (res.get("schemes", []) or [])[:2]:
            steps = s.get("process_hi") if hi else s.get("process_en")
            schemes_info.append({"key": s.get("key", ""),
                                 "next_step": (steps or [""])[0]})
        section = guidance_mod.adaptive_section(
            query, intent, (intent_res or {}).get("entities", {}) or {},
            schemes_info, lang,
            guidance_mod.cited_numbers(resp.get("citations", [])))
        if section:
            resp["text"] = guidance_mod.insert_before_footer(resp["text"], section)
            resp["guidance_adaptive"] = True
    except Exception:
        pass
    return resp


def answer(query: str, lang: str | None = None, context: dict | None = None) -> dict:
    """One RAG/catalogue SQLite connection per turn (issue #4 P1-10)."""
    holder = _RagConnHolder()
    try:
        return _answer_inner(query, lang, context, holder)
    finally:
        holder.close()


def _answer_inner(query: str, lang: str | None = None, context: dict | None = None,
                  holder: _RagConnHolder | None = None) -> dict:
        lang = lang or detect_lang(query)
        hi = lang == "hi"
        ctx = threadmod.normalize_context(context)
        ql = query.lower()
        t = _cfg()
        if any(w in ql for w in RESET_WORDS):
            ctx = threadmod.reset_context()
        if any(w in ql for w in FORCE_WORDS):
            ctx = threadmod.with_force(ctx)

        # NLU intent + conversational memory (observable, behaviour-preserving:
        # journey branching below still owns routing; these only tag responses
        # and feed retrieval/guidance enhancements).
        try:
            intent_res = nlu_mod.classify(query, ctx["history"])
        except Exception:
            intent_res = {"intent": "general", "confidence": "low",
                          "scores": {}, "entities": {"is_numbers": [],
                          "product_terms": [], "stage": ""}}
        try:
            context_summary = memory_mod.summarize_thread(ctx["history"])
        except Exception:
            context_summary = ""

        def _tag(resp: dict) -> dict:
            resp["intent"] = intent_res.get("intent", "general")
            resp["intent_confidence"] = intent_res.get("confidence", "low")
            resp["context_summary"] = context_summary
            return resp

        def _shared_conn(rcfg: dict | None = None):
            try:
                from .rag_config import load_rag_config
                path = (rcfg or load_rag_config()).get("db_path")
            except Exception:
                path = None
            return holder.get(path) if holder is not None else None

        # RAG pre-lookup (query-only) so full-text refusals can be superseded
        # by corpus evidence when BIS_RAG_ENABLED=1.
        rag_evidence, rag_cfg = _rag_lookup(query, _conn=_shared_conn())

        # 1. never-infer gate (current query)
        kind = check_never_infer(query)
        fulltext_waived = False
        if kind:
            # Corpus-backed full-text may divert to extractive corpus answers
            # when evidence exists; keep the kind so that path always runs.
            if kind in ("full_text", "clause_verbatim") and rag_evidence \
                    and _rag_relevant(query, rag_evidence):
                fulltext_waived = True
            else:
                r = _base(lang, refused=True, kind=kind, pii=find_pii(query))
                r["text"] = ((REFUSAL_HI if hi else REFUSAL_EN)[kind]
                             + "\n\n" + _DIVIDER + "\n" + BIS_CARE)
                return _tag(r)

        # 2. topic change: the current query alone strongly names an IS that
        # differs from the thread's topic -> fresh thread. The old side needs no
        # strength threshold: a weak opener (e.g. `steel bottle`) followed by a
        # direct new topic (e.g. `OPC 53 cement`) must not fuse both standards
        # into one answer (issue #4 P0-6).
        res_now = retrieve(query)
        top_now = res_now["candidates"][0] if res_now["candidates"] else None
        if ctx["history"] and top_now and top_now["score"] >= t["direct_score"]:
            res_old = retrieve(" ".join(ctx["history"]))
            top_old = res_old["candidates"][0] if res_old["candidates"] else None
            if top_old is None or top_old["std"]["is_number"] != top_now["std"]["is_number"]:
                ctx = threadmod.reset_context(force=ctx["force"])

        combined = threadmod.combined_query(ctx["history"], query)
        res = retrieve(combined)
        cands = res["candidates"]
        a = assess(combined, cands, ctx, t)
        top, st, ss = a["top"], a["st"], a["ss"]
        exact, strong, weak = a["exact"], a["strong"], a["weak"]
        unfilled, direct = a["unfilled"], a["direct"]

        # Refresh RAG evidence with history-aware context (expanded query keeps
        # follow-ups like "1 litre" grounded in the thread's product terms).
        try:
            retrieval_query = memory_mod.expand_query(combined, ctx["history"])
        except Exception:
            retrieval_query = combined
        if rag_cfg.get("enabled") and retrieval_query != query:
            try:
                ev2, _ = _rag_lookup(retrieval_query, _conn=_shared_conn(rag_cfg))
                if ev2:
                    rag_evidence = ev2
            except Exception:
                pass

        # Corpus decision: prefer grounded corpus answers when they add value,
        # otherwise keep the deterministic metadata mode as fallback/primary.
        if rag_evidence and _rag_relevant(combined, rag_evidence):
            rag_exact = any(e.get("exact_match") for e in rag_evidence)
            journey_q = (_has_lab_hint(ql)
                         or any(h in ql for h in HALLMARK_HINTS + SCHEME_HINTS + CLUB_HINTS))
            bypassed_fulltext = fulltext_waived
            # Curated clarification wins over weak corpus co-occurrence hits:
            # only divert vague queries to the corpus when metadata has no
            # grounded candidate of its own.
            meta_grounded = any((c.get("hits") or c.get("score", 0) >= t.get("grounded_score", 10))
                                for c in cands[:2])
            if bypassed_fulltext or rag_exact or (
                    not direct and not journey_q and not meta_grounded):
                from .rag_answer import build_rag_answer
                try:
                    from .rag_config import load_llm_config
                    llm_cfg = load_llm_config()
                except Exception:
                    llm_cfg = {}
                r = build_rag_answer(query, lang, rag_evidence, llm_cfg,
                                     extractive_only=bypassed_fulltext)
                # Fuse: keep strong metadata citations alongside corpus sources
                # (both retrieval tiers visible, corpus primary).
                try:
                    for c in cands[:2]:
                        if c["hits"] or c["score"] >= t.get("fusion_strong_score", 15.0):
                            fc = format_citation(c["std"])
                            if fc not in r["citations"]:
                                r["citations"].append(fc)
                except Exception:
                    pass
                return _checked(_tag(r), res, rag_evidence)

        if fulltext_waived:
            r = _base(lang, refused=True, kind=kind, pii=find_pii(query))
            r["text"] = ((REFUSAL_HI if hi else REFUSAL_EN)[kind]
                         + "\n\n" + _DIVIDER + "\n" + BIS_CARE)
            return _tag(r)

        # Material contradiction (e.g. plastic bottle vs steel-flask IS): never recommend,
        # never interrogate about the wrong subtypes — state the coverage gap at once.
        # This check intentionally ignores `exact`: naming an IS number the user typed
        # does not license contradicting its own scope (issue #4 P0-5).
        if top and (strong or weak or exact):
            mat = material_mismatch(top["std"]["is_number"], combined)
            if mat:
                return _checked(_tag(_coverage_gap(top["std"], mat, query, lang, hi)), res,
                                rag_evidence)

        journey = (_has_lab_hint(ql)
                   or any(h in ql for h in HALLMARK_HINTS + SCHEME_HINTS + CLUB_HINTS))
        if direct or not weak or (journey and not strong):
            fr = _final(query, combined, res, lang, hi, ctx, top, t)
            if fr.get("kind") == "no_source":
                # Novel product outside curated + corpus coverage: consult the
                # 24k catalogue before refusing.
                cat = _maybe_catalogue(query, retrieval_query, lang,
                                     _conn=_shared_conn(rag_cfg))
                if cat is not None:
                    return _checked(_tag(cat), res, rag_evidence)
            return _checked(_tag(_maybe_enhance(
                _attach_rag_sources(fr, rag_evidence, combined),
                query, intent_res, res, lang)), res, rag_evidence)

        # Novel-product check before interrogation: when the curated KB has no
        # grounded candidate but the 24k catalogue matches strongly, recommend
        # from the catalogue instead of asking irrelevant slot questions.
        # (Curated clarification still wins whenever it is grounded, and journey
        # queries never divert.)
        if not _strongly_grounded(cands, t) and not (_has_lab_hint(ql) or any(
                h in ql for h in HALLMARK_HINTS + SCHEME_HINTS + CLUB_HINTS)):
            cat = _maybe_catalogue(query, retrieval_query, lang, strong_only=True,
                                     _conn=_shared_conn(rag_cfg))
            if cat is not None:
                return _checked(_tag(cat), res, rag_evidence)

        # 3. insufficient context -> ask, don't recommend
        pool = [c for c in cands[:2] if c["score"] >= t["clarify_floor"]]
        if not pool and weak and top:
            pool = [top]  # weak/slot-grounded top still yields its unfilled slots
        questions: list[dict] = []
        seen: set[str] = set()
        for c in pool:
            for s in unfilled_slots(c["std"]["is_number"], combined):
                if s["key"] in seen or len(questions) >= t["max_questions_per_turn"]:
                    continue
                seen.add(s["key"])
                opts = [{"label": (o["label_hi"] if hi else o["label_en"]), "send": o["label_en"]}
                        for o in s.get("options", [])]
                questions.append({"slot": s["key"], "text": s["q_hi"] if hi else s["q_en"],
                                  "options": opts})
        if not questions:  # safety net: nothing left to ask -> answer
            fr = _final(query, combined, res, lang, hi, ctx, top, t)
            if fr.get("kind") == "no_source":
                cat = _maybe_catalogue(query, retrieval_query, lang,
                                     _conn=_shared_conn(rag_cfg))
                if cat is not None:
                    return _checked(_tag(cat), res, rag_evidence)
            return _checked(_tag(_maybe_enhance(
                _attach_rag_sources(fr, rag_evidence, combined),
                query, intent_res, res, lang)), res, rag_evidence)

        fills = fills_for(top["std"]["is_number"], combined)
        known = [{"slot": k, "value": (v["label_hi"] if hi else v["label_en"])}
                 for k, v in fills.items()]
        lines = [("Mujhe sahi manak chunne ke liye thodi aur jankari chahiye — "
                  "kripya in sawalon ke jawab den:" if hi else
                  "I need a bit more detail before I can narrow down the standard — please answer:")]
        if not strong:
            lines.append("")
            lines.append("Note: my coverage here is thin — if these questions don't fit your product, "
                         "tell me and I'll point you to the right BIS search instead." if not hi else
                         "Note: is kshetra me mera coverage seemit hai.")
        for i, q in enumerate(questions, 1):
            lines.append("")
            lines.append(f"{i}. {q['text']}")
            for o in q["options"]:
                lines.append(f"   - {o['label']}")
        if known:
            lines.append("")
            lines.append("Ab tak maloom:" if hi else "Known so far:")
            for k in known:
                lines.append(f"- {k['slot']} = {k['value']}")
        lines.append("")
        area = top["std"]
        lines.append("Sambhavit kshetra (pushti ke baad hi IS naam diya jayega):" if hi else
                     "Possible area (IS number only after you confirm):")
        lines.append(f"- {area['title_en']}")
        lines.append(f"- Source: {area['source_url']}")
        lines.extend(_footer(hi, with_disclaimer=False))
        r = _base(lang, kind="needs_info", pii=find_pii(query), needs_info=True,
                  questions=questions, known=known,
                  citations=[format_citation(area)],
                  context={"history": threadmod.append_turn(ctx["history"], query),
                           "rounds": threadmod.next_rounds(ctx["rounds"])})
        r["text"] = "\n".join(lines)
        return _checked(_tag(_attach_rag_sources(r, rag_evidence, combined)), res, rag_evidence)


def _coverage_gap(std: dict, material: str, query: str, lang: str, hi: bool) -> dict:
    if hi:
        head = f"**{std['is_number']}:{std['year']}** — {std['title_en']}"
        body = [
            head,
            f"- Yah {material} utpadon ke liye nahin hai.",
            f"- Mere vartaman KB me {material} utpadon ke liye koi BIS srot nahin hai, "
            "isliye andaza nahin lagaunga.",
            f"- Know-Your-Standard par khojen: {_PORTAL}",
        ]
    else:
        head = f"**{std['is_number']}:{std['year']}** — {std['title_en']}"
        body = [
            head,
            f"- Covers {std['title_en'].lower()} — not {material} products.",
            f"- My current KB has no BIS source for {material} products, so I won't guess.",
            f"- Search Know-Your-Standard: {_PORTAL}",
        ]
    body.extend(_footer(hi, with_disclaimer=False))
    r = _base(lang, refused=True, kind="coverage_gap", pii=find_pii(query),
              citations=[format_citation(std)], context={"history": [], "rounds": 0})
    r["text"] = "\n".join(body)
    return r


def _gate_fail(resp: dict, kind: str = "verifier_fail") -> dict:
    if kind in REFUSAL_EN:
        hi = resp.get("lang") == "hi"
        text = ((REFUSAL_HI if hi else REFUSAL_EN)[kind]
                + "\n\n" + _DIVIDER + "\n" + BIS_CARE)
    else:
        text = ("I can't stand behind that answer — a citation check failed. "
                "Please rephrase or check Know-Your-Standard directly."
                "\n\n" + _DIVIDER + "\n" + BIS_CARE)
    safe = _base(resp.get("lang", "en"), refused=True, kind=kind,
                 pii=resp.get("pii", {}), context={"history": [], "rounds": 0})
    safe["text"] = text
    return safe


def _checked(resp: dict, res: dict, rag_evidence: list | None = None) -> dict:
    """Enforce never-infer + citation verifier on every outbound answer."""
    from .verifier import verify, section_map
    body = (resp.get("text") or "").split(_DIVIDER, 1)[0]
    nk = check_never_infer(body)
    # Extractive corpus answers may quote paid-adjacent passages; full-text
    # never-infer on the query is already waived. Still refuse cert/licence
    # claims in generated or quoted text.
    if nk and not (resp.get("kind") in ("corpus_answer", "catalogue_answer")
                   and nk in ("full_text", "clause_verbatim")):
        return _gate_fail(resp, nk)
    try:
        stds = [c["std"] for c in res.get("candidates", [])]
        refs = section_map(stds)
        extra_cits = list(resp.get("citations") or [])
        for e in (rag_evidence or []):
            num = str(e.get("standard_number") or "")
            if num:
                extra_cits.append(num)
        # Extractive `> quotes` are sourced passages, not assistant claims.
        # LLM/prose lines are still verified against cited standard numbers only.
        probe_body = "\n".join(
            ln for ln in body.splitlines() if not ln.lstrip().startswith(">"))
        probe = dict(resp)
        probe["text"] = probe_body
        probe["citations"] = extra_cits
        viols = verify(probe, refs)
    except Exception:
        viols = ["verifier_error"]
    if resp.get("kind") in ("corpus_answer", "catalogue_answer") and not resp.get("citations"):
        viols = list(viols) + ["IS claims with zero citations"]
    if viols:
        return _gate_fail(resp, "verifier_fail")
    return resp


def _final(query: str, combined: str, res: dict, lang: str, hi: bool,
           ctx: dict, top: dict | None, t: dict) -> dict:
    ql = query.lower()
    ql_c = combined.lower()
    lab_hit = _has_lab_hint(ql_c)
    cands = res["candidates"]
    lines: list[str] = []
    citations: list[str] = []
    assumptions: list[str] = []

    if any(h in ql_c for h in HALLMARK_HINTS):
        lines.append("**Hallmarking (HUID)**")
        lines.append("- Jeweller registration → AHC testing → 6-digit HUID → verify on BIS Care app."
                     if not hi else "- Jeweller panjikaran → AHC jaanch → 6-ank HUID → BIS Care app par satyapan.")
        lines.append("- Source: https://www.bis.gov.in/hallmarking-overview/ (last-checked 2026-09-18)")
        lines.append("")
        citations.append("BIS Hallmarking overview — https://www.bis.gov.in/hallmarking-overview/")
    if lab_hit:
        lines.append("**BIS labs (LIMS)**" if not hi else "**BIS prayogshala (LIMS)**")
        lines.append("- Confirm IS-wise scope on LIMS before sending samples: https://lims.bis.gov.in/home/search_is_number/"
                     if not hi else "- Namuna bhejne se pehle LIMS par scope pusht karen: https://lims.bis.gov.in/home/search_is_number/")
        lines.append("")
        citations.append("BIS LIMS IS-wise facility — https://lims.bis.gov.in/home/search_is_number/")
    if any(h in ql_c for h in CLUB_HINTS):
        lines.append("**Standards Clubs / training**")
        lines.append("- Standards Clubs/training: see BIS training calendar https://www.bis.gov.in/training-2/training-programmes/ — ask your school nodal officer."
                     if not hi else "- Standards Club/prashikshan: BIS training calendar dekhen, school nodal adhikari se sampark karen.")
        lines.append("")
        citations.append("BIS training — https://www.bis.gov.in/training-2/training-programmes/")
    if any(h in ql_c for h in SCHEME_HINTS) and res["schemes"]:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("**Scheme**" if not hi else "**Yojana**")
        for s in res["schemes"][:2]:
            name = s["name_hi"] if hi else s["name_en"]
            lines.append(f"- **{s['key']}: {name}** — {s['source_url']}")
            steps = s["process_hi"] if hi else s["process_en"]
            lines.append("  - Steps: " + " → ".join(steps[:4]) + " …")
            citations.append(f"{s['key']} — {s['source_url']}")
        lines.append("")

    gfloor = t.get("grounded_score", 10)
    grounded = [c for c in cands if c["hits"] or c["score"] >= gfloor]
    forced = bool(ctx.get("force") or ctx.get("rounds", 0) >= t["max_rounds"])
    if forced and not grounded:
        # "Answer with assumptions" must answer, not refuse: admit weak candidates
        # so assumptions can be stated explicitly (material mismatches still filtered).
        grounded = [c for c in cands
                    if (c["hits"] or c["score"] >= t["weak_floor"])
                    and not material_mismatch(c["std"]["is_number"], combined)]
    if grounded and (not lines or top):
        if lines and lines[-1] != "":
            lines.append("")
        if top and (ctx["force"] or ctx["rounds"] >= t["max_rounds"]):
            unf = unfilled_slots(top["std"]["is_number"], combined)
            if unf:
                assumptions = [(u["q_hi"] if hi else u["q_en"]) for u in unf[:3]]
                lines.append("Answering with assumptions — you didn't specify these, still confirm with BIS:"
                             if not hi else "Anuman par uttar — yah vivaran aapne nahin diya, BIS se pusht karen:")
                lines.extend(f"- {a}" for a in assumptions)
                lines.append("")
        lines.append(STRINGS["candidates_hi"] if hi else STRINGS["candidates_en"])
        for c in cands[:3]:
            s = c["std"]
            if not (c["hits"] or c["score"] >= gfloor or (forced and c in grounded)):
                continue
            if material_mismatch(s["is_number"], combined):
                continue  # never present a materially contradicted standard
            if s["status"] == "Withdrawn":
                lines.append(f'- Warning: {s["is_number"]}:{s["year"]} is **Withdrawn** — do NOT use for manufacture.')
                citations.append(format_citation(s))
                continue
            scope = s["scope_hi"] if hi else s["scope_en"]
            lines.append(f'- **{s["is_number"]}:{s["year"]}** ({c["confidence"]} confidence) — {s["title_en"]}. {scope}')
            lines.append(f'  - Scheme: {s["scheme"]}')
            citations.append(format_citation(s))
        if top and top["std"]["status"] != "Withdrawn":
            unf = unfilled_slots(top["std"]["is_number"], combined)
            if unf and not assumptions:
                lines.append("")
                lines.append("Still to confirm:" if not hi else "Abhi pusht karna baaki:")
                lines.extend(f"- {(u['q_hi'] if hi else u['q_en'])}" for u in unf[:3])
    if not lines and not citations:
        gl = res["glossary"][:2]
        if gl:  # explainable from KB glossary -> answer, don't refuse
            out = [f'- Meaning of **{g["term"]}**: {g["hi"] if hi else g["en"]}' for g in gl]
            out.extend(_footer(hi, with_disclaimer=True))
            r = _base(lang, kind="glossary", pii=find_pii(query),
                      context={"history": [], "rounds": 0})
            r["text"] = "\n".join(out)
            return r
        r = _base(lang, refused=True, kind="no_source", pii=find_pii(query),
                  context={"history": [], "rounds": 0})
        r["text"] = ((STRINGS["no_source_hi"] if hi else STRINGS["no_source_en"])
                     + f"\n\nSearch Know-Your-Standard: {_PORTAL}"
                     + "\n\n" + _DIVIDER + "\n" + BIS_CARE)
        return r

    matched_gloss = [g for g in res["glossary"][:2]
                     if g["term"].lower() in combined.lower() or g["term"].lower() in ql]
    if matched_gloss:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("Terms:" if not hi else "Shabdarth:")
        for g in matched_gloss:
            lines.append(f'- Meaning of **{g["term"]}**: {g["hi"] if hi else g["en"]}')

    while lines and lines[-1] == "":
        lines.pop()
    lines.extend(_footer(hi, with_disclaimer=True))
    r = _base(lang, kind="answered", pii=find_pii(query), citations=citations,
              assumptions=assumptions, context={"history": [], "rounds": 0})
    r["text"] = "\n".join(lines)
    return r
