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


def answer(query: str, lang: str | None = None, context: dict | None = None) -> dict:
    lang = lang or detect_lang(query)
    hi = lang == "hi"
    ctx = threadmod.normalize_context(context)
    ql = query.lower()
    t = _cfg()
    if any(w in ql for w in RESET_WORDS):
        ctx = threadmod.reset_context()
    if any(w in ql for w in FORCE_WORDS):
        ctx = threadmod.with_force(ctx)

    # 1. never-infer gate (current query)
    kind = check_never_infer(query)
    if kind:
        r = _base(lang, refused=True, kind=kind, pii=find_pii(query))
        r["text"] = ((REFUSAL_HI if hi else REFUSAL_EN)[kind] + "\n\n" + BIS_CARE)
        return r

    # 2. topic change: current query alone strongly names a different IS -> fresh thread
    res_now = retrieve(query)
    top_now = res_now["candidates"][0] if res_now["candidates"] else None
    if ctx["history"] and top_now and top_now["score"] >= t["direct_score"]:
        res_old = retrieve(" ".join(ctx["history"]))
        top_old = res_old["candidates"][0] if res_old["candidates"] else None
        if (top_old and top_old["score"] >= t["direct_score"]
                and top_old["std"]["is_number"] != top_now["std"]["is_number"]):
            ctx = threadmod.reset_context(force=ctx["force"])

    combined = threadmod.combined_query(ctx["history"], query)
    res = retrieve(combined)
    cands = res["candidates"]
    a = assess(combined, cands, ctx, t)
    top, st, ss = a["top"], a["st"], a["ss"]
    exact, strong, weak = a["exact"], a["strong"], a["weak"]
    unfilled, direct = a["unfilled"], a["direct"]

    # Material contradiction (e.g. plastic bottle vs steel-flask IS): never recommend,
    # never interrogate about the wrong subtypes — state the coverage gap at once.
    if top and (strong or weak) and not exact:
        mat = material_mismatch(top["std"]["is_number"], combined)
        if mat:
            return _checked(_coverage_gap(top["std"], mat, query, lang, hi), res)

    journey = (_has_lab_hint(ql)
               or any(h in ql for h in HALLMARK_HINTS + SCHEME_HINTS + CLUB_HINTS))
    if direct or not weak or (journey and not strong):
        return _checked(_final(query, combined, res, lang, hi, ctx, top, t), res)

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
        return _checked(_final(query, combined, res, lang, hi, ctx, top, t), res)

    fills = fills_for(top["std"]["is_number"], combined)
    known = [{"slot": k, "value": (v["label_hi"] if hi else v["label_en"])}
             for k, v in fills.items()]
    lines = [("Mujhe sahi manak chunne ke liye thodi aur jankari chahiye — "
              "kripya in sawalon ke jawab den:" if hi else
              "I need a bit more detail before I can narrow down the standard — please answer:")]
    if not strong:
        lines.append("Note: my coverage here is thin — if these questions don't fit your product, "
                     "tell me and I'll point you to the right BIS search instead." if not hi else
                     "Note: is kshetra me mera coverage seemit hai." )
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q['text']}")
        for o in q["options"]:
            lines.append(f"   – {o['label']}")
    if known:
        lines.append("")
        lines.append("Ab tak maloom:" if hi else "Known so far:")
        lines.append(", ".join(f"{k['slot']} = {k['value']}" for k in known))
    lines.append("")
    area = top["std"]
    lines.append(("Sambhavit kshetra (pushti ke baad hi IS naam diya jayega): " if hi else
                  "Possible area (IS number only after you confirm): ")
                 + f"{area['title_en']} — Source: {area['source_url']}")
    lines.append(BIS_CARE)
    r = _base(lang, kind="needs_info", pii=find_pii(query), needs_info=True,
              questions=questions, known=known,
              citations=[format_citation(area)],
              context={"history": threadmod.append_turn(ctx["history"], query),
                       "rounds": threadmod.next_rounds(ctx["rounds"])})
    r["text"] = "\n".join(lines)
    return _checked(r, res)


def _coverage_gap(std: dict, material: str, query: str, lang: str, hi: bool) -> dict:
    portal = "https://www.bis.gov.in/know-your-standard"
    if hi:
        text = (f"{std['is_number']}:{std['year']} — {std['title_en']} — yah {material} utpadon "
                f"ke liye nahin hai. Mere vartaman KB me {material} utpadon ke liye koi BIS srot "
                f"nahin hai, isliye andaza nahin lagaunga. Know-Your-Standard par khojen: {portal}")
    else:
        text = (f"{std['is_number']}:{std['year']} — {std['title_en']} — covers {std['title_en'].lower()}, "
                f"not {material} products. My current KB has no BIS source for {material} products, "
                f"so I won't guess. Search Know-Your-Standard: {portal}")
    r = _base(lang, refused=True, kind="coverage_gap", pii=find_pii(query),
              citations=[format_citation(std)], context={"history": [], "rounds": 0})
    r["text"] = text + "\n\n" + BIS_CARE
    return r


def _checked(resp: dict, res: dict) -> dict:
    """Enforce the citation verifier on every outbound answer (plan §4 stage 3)."""
    from .verifier import verify, section_map
    try:
        stds = [c["std"] for c in res.get("candidates", [])]
        viols = verify(resp, section_map(stds))
    except Exception:
        viols = []
    if viols:
        safe = _base(resp.get("lang", "en"), refused=True, kind="verifier_fail",
                     pii=resp.get("pii", {}), context={"history": [], "rounds": 0})
        safe["text"] = ("I can't stand behind that answer — a citation check failed. "
                        "Please rephrase or check Know-Your-Standard directly.\n\n" + BIS_CARE)
        return safe
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
        lines.append("Source: https://www.bis.gov.in/hallmarking-overview/ (last-checked 2026-09-18)")
        citations.append("BIS Hallmarking overview — https://www.bis.gov.in/hallmarking-overview/")
    if lab_hit:
        lines.append("Confirm IS-wise scope on LIMS before sending samples: https://lims.bis.gov.in/home/search_is_number/"
                     if not hi else "Namuna bhejne se pehle LIMS par scope pusht karen: https://lims.bis.gov.in/home/search_is_number/")
        citations.append("BIS LIMS IS-wise facility — https://lims.bis.gov.in/home/search_is_number/")
    if any(h in ql_c for h in CLUB_HINTS):
        lines.append("Standards Clubs/training: see BIS training calendar https://www.bis.gov.in/training-2/training-programmes/ — ask your school nodal officer."
                     if not hi else "Standards Club/prashikshan: BIS training calendar dekhen, school nodal adhikari se sampark karen.")
        citations.append("BIS training — https://www.bis.gov.in/training-2/training-programmes/")
    if any(h in ql_c for h in SCHEME_HINTS) and res["schemes"]:
        for s in res["schemes"][:2]:
            name = s["name_hi"] if hi else s["name_en"]
            lines.append(f"- **{s['key']}: {name}** — {s['source_url']}")
            steps = s["process_hi"] if hi else s["process_en"]
            lines.append("  Steps: " + " → ".join(steps[:4]) + " …")
            citations.append(f"{s['key']} — {s['source_url']}")

    grounded = [c for c in cands if c["hits"] or c["score"] >= 10]
    forced = bool(ctx.get("force") or ctx.get("rounds", 0) >= t["max_rounds"])
    if forced and not grounded:
        # "Answer with assumptions" must answer, not refuse: admit weak candidates
        # so assumptions can be stated explicitly (material mismatches still filtered).
        grounded = [c for c in cands
                    if (c["hits"] or c["score"] >= t["weak_floor"])
                    and not material_mismatch(c["std"]["is_number"], combined)]
    if grounded and (not lines or top):
        if top and (ctx["force"] or ctx["rounds"] >= t["max_rounds"]):
            unf = unfilled_slots(top["std"]["is_number"], combined)
            if unf:
                assumptions = [(u["q_hi"] if hi else u["q_en"]) for u in unf[:3]]
                lines.append("Answering with assumptions — you didn't specify these, still confirm with BIS:"
                             if not hi else "Anuman par uttar — yah vivaran aapne nahin diya, BIS se pusht karen:")
                lines.extend(f"- {a}" for a in assumptions)
        lines.append(STRINGS["candidates_hi"] if hi else STRINGS["candidates_en"])
        for c in cands[:3]:
            s = c["std"]
            if not (c["hits"] or c["score"] >= 10 or (forced and c in grounded)):
                continue
            if material_mismatch(s["is_number"], combined):
                continue  # never present a materially contradicted standard
            if s["status"] == "Withdrawn":
                lines.append(f'- ⚠️ {s["is_number"]}:{s["year"]} is **Withdrawn** — do NOT use for manufacture.')
                citations.append(format_citation(s))
                continue
            scope = s["scope_hi"] if hi else s["scope_en"]
            lines.append(f'- **{s["is_number"]}:{s["year"]}** ({c["confidence"]} confidence) — {s["title_en"]}. {scope}')
            lines.append(f'  Scheme: {s["scheme"]}')
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
            out = [f'Meaning of **{g["term"]}**: {g["hi"] if hi else g["en"]}' for g in gl]
            out += ["", DISCLAIMER_HI if hi else DISCLAIMER_EN, BIS_CARE]
            r = _base(lang, kind="glossary", pii=find_pii(query),
                      context={"history": [], "rounds": 0})
            r["text"] = "\n".join(out)
            return r
        r = _base(lang, refused=True, kind="no_source", pii=find_pii(query),
                  context={"history": [], "rounds": 0})
        r["text"] = STRINGS["no_source_hi"] if hi else STRINGS["no_source_en"]
        return r

    for g in res["glossary"][:2]:
        if g["term"].lower() not in combined.lower() and g["term"].lower() not in ql:
            continue
        lines.append(f'\nMeaning of **{g["term"]}**: {g["hi"] if hi else g["en"]}')

    lines.append("")
    lines.append(DISCLAIMER_HI if hi else DISCLAIMER_EN)
    lines.append(BIS_CARE)
    r = _base(lang, kind="answered", pii=find_pii(query), citations=citations,
              assumptions=assumptions, context={"history": [], "rounds": 0})
    r["text"] = "\n".join(lines)
    return r
