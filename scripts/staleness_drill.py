"""KB-staleness drill (plan §9, acceptance §10.8 support).

Copies the KB to tmp, publishes a withdrawal for IS 694 through the review queue,
then asserts: answers warn (Withdrawn, do NOT use) and never present it as usable.
The live kb/bis.db is untouched; restore = discard tmp copy (timed drill in memo).

Usage: PYTHONPATH=src python scripts/staleness_drill.py [--db kb/bis.db]
"""
from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # top-level ingest/


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="kb/bis.db")
    args = ap.parse_args()
    from bis_assistant import kb_store
    from ingest import review as reviewmod
    from ingest import snapshot as snapmod

    tmp = Path(tempfile.mkdtemp()) / "drill.db"
    shutil.copy(args.db, tmp)
    conn = kb_store.connect(tmp)
    snap = snapmod.snapshot_raw(conn, "https://www.bis.gov.in/know-your-standard",
                                "drill", note="staleness drill")
    snapmod.diff_against_kb(conn, snap, [{"is_number": "IS 694", "year": "2010",
        "title_en": "PVC Insulated Cables", "status": "Withdrawn"}])
    did = conn.execute("SELECT id FROM pending_diffs WHERE is_number='IS 694'"
                       " AND status='pending' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    reviewmod.cmd_approve(conn, did, by="drill")
    conn.close()

    import os
    os.environ["BIS_RETRIEVAL_KB_BACKEND"] = "sqlite"
    os.environ["BIS_KB_PATH"] = str(tmp)
    from bis_assistant import slots as slotmod
    slotmod.use_db(str(tmp))
    from bis_assistant.assistant import answer
    r = answer("PVC house wiring cable up to 1100V, single core")
    assert "Withdrawn" in r["text"], "drill FAIL: no withdrawal warning"
    assert "do NOT use" in r["text"], "drill FAIL: missing do-not-use"
    assert r["citations"], "drill FAIL: citations required even when warning"
    print("DRILL PASS: IS 694 withdrawal warns with citations, never recommended as usable")
    slotmod._DB_SLOTS = None


if __name__ == "__main__":
    main()
