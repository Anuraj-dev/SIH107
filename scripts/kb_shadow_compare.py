"""Shadow-compare JSON vs SQLite backends over the v1 gold set.

Usage: BIS_KB_PATH=kb/bis.db PYTHONPATH=src python scripts/kb_shadow_compare.py
Exit 1 on any divergence in (top IS, needs_info, refusal). Run before cutover.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant import slots as slotmod
from bis_assistant.assistant import answer

ROOT = Path(__file__).resolve().parents[1]


def run_once() -> list[dict]:
    gold = json.loads((ROOT / "eval" / "gold.json").read_text())
    out = []
    for g in gold:
        r = answer(g["query"], g.get("lang"))
        top = r["citations"][0].split(" — ")[0] if r["citations"] else ""
        out.append({"id": g["id"], "top": top, "needs_info": r["needs_info"],
                    "refused": r["refused"]})
    return out


def main() -> None:
    if "BIS_KB_PATH" not in os.environ:
        print("set BIS_KB_PATH to the SQLite KB first")
        sys.exit(2)
    os.environ["BIS_RETRIEVAL_KB_BACKEND"] = "json"
    base = run_once()
    os.environ["BIS_RETRIEVAL_KB_BACKEND"] = "sqlite"
    slotmod.use_db(os.environ["BIS_KB_PATH"])
    shadow = run_once()
    divs = [b for b, s in zip(base, shadow)
            if (b["top"], b["needs_info"], b["refused"]) != (s["top"], s["needs_info"], s["refused"])]
    print(f"compared {len(base)} queries: {len(divs)} divergences")
    for d in divs:
        s = next(x for x in shadow if x["id"] == d["id"])
        print(f'  id={d["id"]} json={d} sqlite={s}')
    sys.exit(1 if divs else 0)


if __name__ == "__main__":
    main()
