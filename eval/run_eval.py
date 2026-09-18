"""Eval gate: groundedness + citation + refusal + scheme accuracy. Bar: >=90% to ship."""
from __future__ import annotations
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import os as _os

from bis_assistant.assistant import answer

GOLD = json.loads((Path(__file__).parent / "gold.json").read_text_text() if False else (Path(__file__).parent / "gold.json").read_text())


def pin_eval_env() -> dict:
    """Deterministic baseline (issue #4 P1-16): RAG/LLM/catalogue shift
    scores, so they are pinned off unless BIS_EVAL_ALLOW_ENV=1 explicitly
    opts into measuring the live stack. Returns the snapshot for the report."""
    allow = _os.environ.get("BIS_EVAL_ALLOW_ENV") == "1"
    if not allow:
        _os.environ["BIS_RAG_ENABLED"] = "0"
        _os.environ["BIS_CATALOGUE_ENABLED"] = "0"
        _os.environ["BIS_LLM_MODEL"] = ""
        _os.environ["BIS_LLM_API_KEY"] = ""
    snap = {k: _os.environ.get(k, "") for k in
            ("BIS_RAG_ENABLED", "BIS_CATALOGUE_ENABLED", "BIS_LLM_PROVIDER",
             "BIS_LLM_MODEL", "BIS_RETRIEVAL_SCORER", "BIS_RETRIEVAL_KB_BACKEND")}
    snap["llm_key_set"] = bool(_os.environ.get("BIS_LLM_API_KEY"))
    snap["eval_env_pinned"] = not allow
    return snap


def citation_has_url(citations: list) -> bool:
    import re as _re
    return any(_re.search(r"https?://\S+", c or "") for c in citations)


def score_item(g: dict) -> dict:
    r = answer(g["query"], g.get("lang"))
    clarified = False
    if r.get("needs_info") and not g.get("must_refuse"):
        # single-shot eval mode: user answers "use your best judgement"
        r = answer(g["query"], g.get("lang"), {**r["context"], "force": True})
        clarified = True
    text = r["text"]
    ok = True
    reasons = []
    # refusal
    if g.get("must_refuse"):
        if not r["refused"]:
            # items 44/45 are "warn, don't guarantee" — accept either refusal or withdrawn/no-source warning
            if g["id"] in (44, 45) and ("Withdrawn" in text or "won't guess" in text or "I don't have" in text):
                pass
            else:
                ok = False
                reasons.append("should_refuse")
    else:
        if r["refused"] and g.get("must_cite"):
            ok = False
            reasons.append("wrong_refusal")
    # expected IS
    if g.get("expect_is"):
        if g["expect_is"] not in text and not any(g["expect_is"] in c for c in r["citations"]):
            ok = False
            reasons.append(f"missing {g['expect_is']}")
    # expected scheme
    if g.get("expect_scheme"):
        if g["expect_scheme"].lower() not in text.lower():
            ok = False
            reasons.append(f"missing scheme {g['expect_scheme']}")
    # citation required
    if g.get("must_cite") and not r["citations"]:
        ok = False
        reasons.append("missing_citation")
    # citation must point somewhere verifiable, not be a bare label
    if g.get("must_cite") and r["citations"] and not citation_has_url(r["citations"]):
        ok = False
        reasons.append("citation_without_url")
    # disclaimer when answered
    if not r["refused"] and "Informational only" not in text and "Keval jankari" not in text:
        ok = False
        reasons.append("missing_disclaimer")
    return {"id": g["id"], "ok": ok, "reasons": reasons, "clarified": clarified}


def main():
    env = pin_eval_env()
    results = [score_item(g) for g in GOLD]
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    clar = [r["id"] for r in results if r.get("clarified")]
    print(f"Eval: {passed}/{total} = {100*passed/total:.1f}%  (gate: >=90%)")
    print(f"  env: pinned={env['eval_env_pinned']} "
          f"RAG={env['BIS_RAG_ENABLED'] or '0'} catalogue={env['BIS_CATALOGUE_ENABLED'] or '0'} "
          f"llm_model={env['BIS_LLM_MODEL'] or '(none)'} key_set={env['llm_key_set']} "
          f"scorer={env['BIS_RETRIEVAL_SCORER'] or 'default'} kb={env['BIS_RETRIEVAL_KB_BACKEND'] or 'default'}")
    if clar:
        print(f"  single-shot clarification needed on #{clar} (answered with assumptions in eval mode)")
    print(f"  forced-clarify rate: {len(clar)}/{total} = {100*len(clar)/total:.1f}% (reported separately; forced answers still gated)")
    for r in results:
        if not r["ok"]:
            print(f"  FAIL #{r['id']}: {', '.join(r['reasons'])}")
    sys.exit(0 if passed / total >= 0.90 else 1)


if __name__ == "__main__":
    main()
