"""Breadth pipeline tests (fixtures only — no network).

Fixtures are trimmed real captures from 2026-09-18 (see
docs/data-sources-research.md): DG dept table, one DataTables JSON page,
CRS products table, KYS Basic-Details card, LIMS result table.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bis_assistant import kb_store  # noqa: E402
from ingest import assert_crawlable  # noqa: E402
from ingest import breadth as B  # noqa: E402
from ingest import review as reviewmod  # noqa: E402
from ingest import snapshot as snapmod  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "ingest" / "fixtures"
PY = sys.executable


def _import_to(db: Path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    r = subprocess.run([PY, str(ROOT / "scripts" / "import_json_kb.py"),
                        "--db", str(db)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr


# --- normalisation ---------------------------------------------------------


def test_normalize_is_number_variants():
    assert B.normalize_is_number("IS 1121 (Part 1):2023")["is_number"] == "IS 1121"
    assert B.normalize_is_number("IS 1121 (Part 1):2023")["year"] == "2023"
    assert B.normalize_is_number("IS/ISO 6182-7:2004")["is_number"] == "IS 6182-7"
    assert B.normalize_is_number("IS 694:2010")["is_number"] == "IS 694"
    assert B.normalize_is_number("nonsense")["is_number"] == ""


def test_is_key_part_aware():
    assert B.is_key("IS 302-1") == B.is_key("IS 302 (Part 1)")
    assert B.is_key("IS 10500") == ("10500", "")
    assert B.is_key("IS 16102 (Part 2)") != B.is_key("IS 16102-1")


# --- DG dashboard ----------------------------------------------------------


def test_parse_dgdept_table_fixture():
    depts = B.parse_dgdept_table((FIX / "dg-departments.html").read_text())
    by_code = {d["dept_code"]: d for d in depts}
    assert by_code["AYD"]["total"] == 199
    assert by_code["CED"]["total"] == 1904
    assert "Civil Engineering" in by_code["CED"]["dept"]
    assert all(d["list_url"].startswith("https://www.services.bis.gov.in")
               for d in depts)


def test_parse_dg_list_ajax_fixture():
    recs = B.parse_dg_list_ajax((FIX / "dg-list-ajax.json").read_text())
    assert len(recs) == 5
    first = recs[0]
    assert first["is_number"] == "IS 17424 (Part 1)"
    assert first["year"] == "2020"
    assert "Ayurvedic" in first["title_en"]
    assert first["detail_url"].endswith("isdetails_mnd/24887")
    assert first["status"] == "Active"


def test_to_kb_row_schema():
    recs = B.parse_dg_list_ajax((FIX / "dg-list-ajax.json").read_text())
    rec = {**recs[0], "dept": "Ayush Department (AYD)", "dept_code": "AYD"}
    row = B.to_kb_row(rec, "2026-09-18")
    assert row["qco_status"] == "unknown"  # never auto-claim compulsory
    assert row["section_ref"] == ""  # verifier forbids clause numbers
    assert row["source_url"].endswith("isdetails_mnd/24887")
    assert "metadata" in row["source_snippet"]


# --- KYS detail ------------------------------------------------------------


def test_parse_kys_detail_fixture():
    d = B.parse_kys_detail((FIX / "kys-detail.html").read_text())
    assert d["is_number"] == "IS 1121"
    assert d["part"] == "4"
    assert "shear strength" in d["title_en"].lower()
    assert d["department"].startswith("CED")
    assert "CED 06" in d["committee"]
    assert d["supersedes"] == ""


# --- CRS -------------------------------------------------------------------


def test_parse_crs_table_fixture():
    rows = B.parse_crs_table((FIX / "crs-products.html").read_text())
    assert len(rows) == 8
    assert rows[0]["product"].startswith("AMPLIFIERS")
    assert rows[0]["is_raw"] == "IS 616:2017"
    assert B.crs_is_numbers(rows[0]["is_raw"]) == ["IS 616"]
    multi = "IS 616 :2017 OR IS 616:2017 & IS 18112:2025"
    assert B.crs_is_numbers(multi) == ["IS 616", "IS 18112"]


# --- LIMS ------------------------------------------------------------------


def test_lims_url_and_rows():
    url = B.lims_search_url(doc_no="694")
    assert url.startswith("https://lims.bis.gov.in/home/search_is_number/?")
    assert "is_number__doc_no=694" in url
    rows = B.parse_lims_rows((FIX / "lims-search.html").read_text())
    assert len(rows) == 1
    assert "IS 694" in rows[0]["is_no"]
    assert rows[0]["osl"] == "5169204"
    assert rows[0]["charges"] == "20000"


# --- crawl gates -----------------------------------------------------------


def test_crawlable_allows_p0_blocks_p1_p2():
    for ok in (B.DG_MAIN, B.KYS_SEARCH, B.CRS_PRODUCTS, B.LIMS_SEARCH,
               "https://standards.bis.gov.in/website/know-your-standards"):
        assert_crawlable(ok)
    with pytest.raises(ValueError):
        assert_crawlable("https://standardsbis.bsbedge.com/")
    with pytest.raises(ValueError):
        assert_crawlable("https://www.manakonline.in/")
    with pytest.raises(ValueError):
        assert_crawlable("https://example.com/evil.pdf")


# --- queue + review --------------------------------------------------------


def test_queue_breadth_skips_curated_no_missing_noise(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        recs = B.parse_dg_list_ajax((FIX / "dg-list-ajax.json").read_text())
        for r in recs:
            r.update(dept="Ayush Department (AYD)", dept_code="AYD")
        # a breadth row colliding with curated depth must be skipped
        recs.append({"is_number": "IS 10500", "year": "2012",
                     "title_en": "Drinking Water — Specification",
                     "status": "Active", "dept": "FAD", "dept_code": "FAD",
                     "aspect": "", "equivalence": "", "pub_date": "",
                     "detail_url": "", "designation": "IS 10500:2012"})
        snap = kb_store.new_snapshot(conn, "test", "breadth")
        stats = snapmod.queue_breadth_records(conn, snap, recs)
        assert stats["added"] == 5  # IS 17424 Parts 1-5 are distinct keys
        assert stats["skipped_curated"] == 1
        # no missing-upstream rows for curated standards absent from feed
        missing = conn.execute("SELECT COUNT(*) c FROM pending_diffs"
                               " WHERE change_type='missing-upstream'").fetchone()["c"]
        assert missing == 0
    finally:
        conn.close()


def test_queue_breadth_part_aware_dedupe(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        recs = B.parse_dg_list_ajax((FIX / "dg-list-ajax.json").read_text())
        recs.append(dict(recs[0]))  # exact duplicate row in feed
        snap = kb_store.new_snapshot(conn, "test", "breadth")
        stats = snapmod.queue_breadth_records(conn, snap, recs)
        assert stats["added"] == 5
    finally:
        conn.close()


def test_review_approve_all_needs_two_humans(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        snap = kb_store.new_snapshot(conn, "test", "x")
        snapmod.diff_against_kb(conn, snap, [{"is_number": "IS 9999",
            "year": "2020", "title_en": "Some Widget", "status": "Active",
            "source_url": "https://www.bis.gov.in/know-your-standard/"}])
        with pytest.raises(SystemExit):
            reviewmod.cmd_approve_all(conn, "solo", "solo", "added")
        n = reviewmod.cmd_approve_all(conn, "alice", "bob", "added")
        assert n >= 1
        cur = conn.execute("SELECT title_en, department FROM standards"
                           " WHERE is_number='IS 9999' ORDER BY version DESC"
                           " LIMIT 1").fetchone()
        assert cur["title_en"] == "Some Widget"
    finally:
        conn.close()


def test_approve_missing_diff_is_review_error(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        with pytest.raises(reviewmod.ReviewError) as ei:
            reviewmod.cmd_approve(conn, 99999, "alice")
        assert ei.value.http_status == 404
        assert not isinstance(ei.value, SystemExit)
    finally:
        conn.close()


def test_approve_empty_source_url_rejected(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        snap = kb_store.new_snapshot(conn, "test", "x")
        snapmod.diff_against_kb(conn, snap, [{"is_number": "IS 8888",
            "year": "2020", "title_en": "No URL", "status": "Active"}])
        did = conn.execute("SELECT id FROM pending_diffs WHERE is_number='IS 8888'"
                           ).fetchone()["id"]
        with pytest.raises(reviewmod.ReviewError) as ei:
            reviewmod.cmd_approve(conn, did, "alice")
        assert ei.value.http_status == 400
    finally:
        conn.close()


def test_reject_missing_diff_is_review_error(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        with pytest.raises(reviewmod.ReviewError) as ei:
            reviewmod.cmd_reject(conn, 99999)
        assert ei.value.http_status == 404
    finally:
        conn.close()


def test_approve_changed_requires_stored_source_url(tmp_path):
    db = tmp_path / "kb.db"
    _import_to(db)
    conn = kb_store.connect(db)
    try:
        snap = kb_store.new_snapshot(conn, "test", "x")
        conn.execute(
            "INSERT INTO pending_diffs(snapshot_id, change_type, is_number, details_json, status)"
            " VALUES (?,?,?,?,?)",
            (snap, "changed", "IS 694", json.dumps({
                "title_en": "PVC insulated cables",
                "source_url": "",
                "detail_url": "https://www.bis.gov.in/know-your-standard/",
            }), "pending"))
        conn.commit()
        did = conn.execute(
            "SELECT id FROM pending_diffs WHERE is_number='IS 694' AND change_type='changed'"
            " ORDER BY id DESC").fetchone()["id"]
        with pytest.raises(reviewmod.ReviewError) as ei:
            reviewmod.cmd_approve(conn, did, "alice")
        assert ei.value.http_status == 400
    finally:
        conn.close()
