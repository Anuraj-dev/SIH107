"""Run the fixed 50-question acceptance set against a configured model.

Export the BIS_LLM_* settings before running. BIS_EVAL_ALLOW_ENV=1 makes the
expected-LLM check strict; it does not load credentials or enable a fallback.
Only aggregate/check metadata is written to results.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bis_assistant.assistant import answer

DATA = ROOT / "eval/datasets/v3/groq-chatbot-50.json"


class _GenerationFailureCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() != "grounded generation unavailable; using extractive fallback":
            return
        ctx = getattr(record, "ctx", {}) or {}
        self.events.append({key: ctx.get(key) for key in
                            ("provider", "model", "attempts", "reason")})


def _standard_key(value: str) -> str:
    value = re.sub(r"\(\s*part\s*(\d+)\s*\)", r"-\1", value, flags=re.I)
    return re.sub(r"\s+", "", value).upper()


def run_case(case: dict) -> dict:
    response = answer(case["query"], case.get("lang"))
    clarified = False
    if response.get("needs_info") and not case.get("must_refuse"):
        response = answer(case["query"], case.get("lang"),
                          {**response["context"], "force": True})
        clarified = True
    text = response.get("text", "")
    citations = response.get("citations") or []
    sources = response.get("sources") or response.get("rag_evidence") or []
    checks = {}
    expected_standards = case.get("expect_is_all") or (
        [case["expect_is"]] if case.get("expect_is") else [])
    if expected_standards:
        checks["standard"] = all(
            any(_standard_key(_standard) in _standard_key(value)
                for value in [text, *citations])
            for _standard in expected_standards)
    else:
        checks["standard"] = None
    if case.get("expect_scheme"):
        checks["scheme"] = case["expect_scheme"].lower() in text.lower()
    else:
        checks["scheme"] = None
    if case.get("must_refuse"):
        withdrawn_warning = "withdrawn" in text.lower() and "do not use" in text.lower()
        checks["refusal"] = bool(withdrawn_warning or response.get("refused") or response.get("kind") in
                                  ("full_text", "clause_verbatim", "certification_claim",
                                   "licence_guarantee", "lab_result", "legal_advice",
                                   "coverage_gap", "no_source"))
    else:
        checks["refusal"] = not response.get("refused")
    checks["citation"] = (bool(citations) and any("http" in c for c in citations)) \
        if case.get("must_cite") else None
    checks["llm"] = response.get("rag_used_llm") is True
    checks["expected_llm"] = checks["llm"] if case.get("expect_llm") else None
    checks["sources"] = bool(sources)
    checks["disclaimer"] = ("Informational only" in text or "Keval jankari" in text) \
        if not response.get("refused") else None
    hard_checks = [v for k, v in checks.items()
                   if k not in ("llm", "sources", "disclaimer", "expected_llm") and v is not None]
    if os.environ.get("BIS_EVAL_ALLOW_ENV") == "1" and case.get("expect_llm"):
        hard_checks.append(checks["expected_llm"])
    return {"id": case["id"], "category": case["category"], "ok": all(hard_checks),
            "checks": checks, "kind": response.get("kind", ""),
            "rag_used_llm": bool(response.get("rag_used_llm")), "clarified": clarified}


def main() -> int:
    live = os.environ.get("BIS_EVAL_ALLOW_ENV") == "1"
    cases = json.loads(DATA.read_text(encoding="utf-8"))
    results = []
    failure_capture = _GenerationFailureCapture()
    api_logger = logging.getLogger("bis.api")
    old_level = api_logger.level
    api_logger.setLevel(logging.WARNING)
    api_logger.addHandler(failure_capture)
    for i, case in enumerate(cases, 1):
        failure_capture.events.clear()
        result = run_case(case)
        result["llm_failures"] = list(failure_capture.events)
        results.append(result)
        print(f"{i:02}/{len(cases)} {result['id']} {'PASS' if result['ok'] else 'FAIL'} "
              f"kind={result['kind']} llm={result['rag_used_llm']}"
              + (f" fallback={failure_capture.events[-1]['reason']}"
                 if failure_capture.events else ""))
    api_logger.removeHandler(failure_capture)
    api_logger.setLevel(old_level)
    total = sum(r["ok"] for r in results)
    llm_n = sum(r["rag_used_llm"] for r in results)
    failed = [r["id"] for r in results if not r["ok"]]
    print(f"Acceptance: {total}/{len(results)} hard checks passed; LLM used on {llm_n} cases; "
          f"mode={'live' if live else 'local'}")
    if failed:
        print("Failed cases: " + ", ".join(failed))
    out = ROOT / "eval/results"
    out.mkdir(exist_ok=True)
    (out / "groq-chatbot-50-latest.json").write_text(
        json.dumps({"live": live, "passed": total, "total": len(results),
                    "llm_used": llm_n, "results": results}, indent=2) + "\n",
        encoding="utf-8")
    return 0 if total == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
