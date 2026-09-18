import json
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant import kb_store
from bis_assistant import slots as slotmod
from ingest import snapshot as snapmod

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "ingest" / "fixtures"
PY = sys.executable


def _import_to(db: Path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    r = subprocess.run([PY, str(ROOT / "scripts" / "import_json_kb.py"),
                        "--db", str(db)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_import_counts(tmp_path):
    _import_to(tmp_path / "kb.db")
    conn = kb_store.connect(tmp_path / "kb.db")
    try:
        assert len(kb_store.load_standards(conn)) == 16
        assert len(kb_store.load_schemes(conn)) == 4
        assert len(kb_store.load_labs(conn)["samples"]) == 5
        assert len(kb_store.load_glossary(conn)) == 6
        assert "IS 17803" in kb_store.load_slots(conn)
        assert kb_store.load_labs(conn)["lims_search"].startswith("https://lims.bis.gov.in")
    finally:
        conn.close()


def test_sqlite_backend_matches_json(tmp_path, monkeypatch):
    from bis_assistant.assistant import answer
    db = tmp_path / "kb.db"
    _import_to(db)
    monkeypatch.setenv("BIS_RETRIEVAL_KB_BACKEND", "sqlite")
    monkeypatch.setenv("BIS_KB_PATH", str(db))
    slotmod.use_db(str(db))
    try:
        r = answer("vacuum insulated stainless steel water bottle, 1 litre")
        assert "IS 17803" in r["text"] and r["citations"]
        r2 = answer("LED lamp self-ballasted general lighting 9W B22")
        assert "IS 16102-1" in r2["text"]
    finally:
        slotmod._DB_SLOTS = None


def test_parser_reads_fixture():
    recs = snapmod.parse_records((FIX / "know-your-standard.html").read_text())
    by_no = {r["is_number"]: r for r in recs}
    assert by_no["IS 694"]["status"] == "Active"
    assert by_no["IS 10500"]["year"] == "2012"


def test_diff_detects_changed_and_added(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        snap = snapmod.snapshot_raw(
            conn, "https://www.bis.gov.in/know-your-standard",
            (FIX / "know-your-standard-changed.html").read_text(), note="test")
        changes = snapmod.diff_against_kb(conn, snap, snapmod.parse_records(
            (FIX / "know-your-standard-changed.html").read_text()))
        by_no = {c["is_number"]: c for c in changes}
        assert by_no["IS 694"]["change_type"] == "changed"
        assert by_no["IS 16200"]["change_type"] == "added"
        pend = conn.execute("SELECT COUNT(*) c FROM pending_diffs WHERE status='pending'").fetchone()["c"]
        assert pend == len(changes) and pend >= 2
    finally:
        conn.close()


def test_review_approve_bumps_version(tmp_path):
    from ingest import review as reviewmod
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        snap = snapmod.snapshot_raw(conn, "https://www.bis.gov.in/know-your-standard",
                                    "x", note="test")
        snapmod.diff_against_kb(conn, snap, [{"is_number": "IS 694", "year": "2010",
            "title_en": "PVC Insulated Cables", "status": "Superseded"}])
        did = conn.execute("SELECT id FROM pending_diffs WHERE is_number='IS 694'").fetchone()["id"]
        reviewmod.cmd_approve(conn, did, by="tester")
        cur = conn.execute("SELECT status, version FROM standards WHERE is_number='IS 694'"
                           " ORDER BY version DESC LIMIT 1").fetchone()
        assert cur["status"] == "Superseded" and cur["version"] == 2
    finally:
        conn.close()
