"""A/B: keyword baseline vs BM25 challenger over the v1 gold set.

Usage: PYTHONPATH=src python eval/ab_compare.py
Reports per-item outcome agreement + both gates. BM25_SCALE calibration: adjust in
scorers.py until gold direct-answer items stay direct and vague items still clarify.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant.assistant import answer

ROOT = Path(__file__).resolve().parents[1]


def outcome(g: dict) -> tuple:
    r = answer(g["query"], g.get("lang"))
    if r.get("needs_info") and not g.get("must_refuse"):
        r = answer(g["query"], g.get("lang"), {**r["context"], "force": True})
    top = r["citations"][0].split(" — ")[0] if r["citations"] else ""
    return (top, r["refused"])


def main() -> None:
    gold = json.loads((ROOT / "eval" / "gold.json").read_text())
    outs = {}
    for scorer in ("keyword", "bm25"):
        os.environ["BIS_RETRIEVAL_SCORER"] = scorer
        outs[scorer] = [outcome(g) for g in gold]
    agree = sum(1 for a, b in zip(outs["keyword"], outs["bm25"]) if a == b)
    print(f"scorer agreement: {agree}/{len(gold)}")
    for g, a, b in zip(gold, outs["keyword"], outs["bm25"]):
        if a != b:
            print(f'  id={g["id"]} keyword={a} bm25={b} :: {g["query"][:60]}')
    del os.environ["BIS_RETRIEVAL_SCORER"]


if __name__ == "__main__":
    main()
