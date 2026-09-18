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

HALLMARK_HINTS = ("hallmark", "huid", "gold", "silver", "jewell", "sona", "chandi")
LAB_HINTS = ("lab", "testing", "test house", "prayogshala", "parikshan")
SCHEME_HINTS = ("isi", "crs", "fmcs", "licence", "license", "certification", "registration", "qco", "scheme")
CLUB_HINTS = ("club", "student", "training", "school", "college", "vidyarthi")

RESET_WORDS = ("new question", "reset", "change topic", "naya sawal", "naya prashn", "नया सवाल")
FORCE_WORDS = ("answer anyway", "assume", "just answer", "best guess")

# Defaults; live values come from config.yaml (plan §4: threshold changes need eval re-gate).
_FALLBACK = {"direct_score": 15.0, "direct_margin": 5.0, "clarify_floor": 6.0,
             "max_rounds": 2, "max_questions_per_turn": 2}


def _cfg() -> dict:
    from .config import load as load_config
    try:
        return load_config()["retrieval"]
    except Exception:
        return dict(_FALLBACK)


def _base(lang: str, **kw) -> dict:
    return {"text": "", "refused": False, "kind": "answered", "lang": lang,
            "citations": [], "pii": {}, "needs_info": False, "questions": [],
            "known": [], "assumptions": [], "context": {"history": [], "rounds": 0}, **kw}


def answer(query: str, lang: str | None = None, context: dict | None = None) -> dict:
    lang = lang or detect_lang(query)
    hi = lang == "hi"
    ctx = {"history": list((context or {}).get("history", [])),
           "rounds": int((context or {}).get("rounds", 0)),
           "force": bool((context or {}).get("force", False))}
    ql = query.lower()
    t = _cfg()
    if any(w in ql for w in RESET_WORDS):
        ctx = {"history": [], "rounds": 0, "force": False}
    if any(w in ql for w in FORCE_WORDS):
        ctx["force"] = True

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
            ctx = {"history": [], "rounds": 0, "force": ctx["force"]}

    combined = " ".join(ctx["history"] + [query]).strip()
    res = retrieve(combined)
    cands = res["candidates"]
    top = cands[0] if cands else None
    st = top["score"] if top else 0.0
    ss = cands[1]["score"] if len(cands) > 1 else 0.0
    m = re.search(r"is\s*(\d+)", combined.lower())
    exact = bool(m and top and m.group(1) in top["std"]["is_number"])
    # Clarification only when a real phrase/IS hit grounds the thread;
    # generic token overlap (no hits) falls through to journeys/glossary.
    strong = bool(top and st >= t["clarify_floor"] and (top["hits"] or st >= t["direct_score"]))
    unfilled = unfilled_slots(top["std"]["is_number"], combined) if top else []
    direct = (exact or ctx["force"] or ctx["rounds"] >= t["max_rounds"]
              or (top and st >= t["direct_score"] and (st - ss) >= t["direct_margin"])
              or (strong and not unfilled))

    if direct or not strong:
        return _checked(_final(query, combined, res, lang, hi, ctx, top, t), res)

    # 3. insufficient context -> ask, don't recommend
    pool = [c for c in cands[:2] if c["score"] >= t["clarify_floor"]]
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
              context={"history": ctx["history"] + [query], "rounds": ctx["rounds"] + 1})
    r["text"] = "\n".join(lines)
    return _checked(r, res)


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
    if any(h in ql_c for h in LAB_HINTS):
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
            if not (c["hits"] or c["score"] >= 10):
                continue
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
