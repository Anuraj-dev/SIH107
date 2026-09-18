"""Snapshot + parse + diff. Parsers run against fixtures in tests; live crawl needs
config ingest.live_crawl_enabled=true AND human review before publish (plan §3)."""
from __future__ import annotations
import json
import re
import sqlite3
from . import assert_allowlisted

# Minimal record format parsers understand (fixtures mirror BIS page fragments).
RECORD_RE = re.compile(
    r"IS\s*(?P<num>\d+(?:-\d+)?)\s*:\s*(?P<year>\d{4})\s*\|\s*(?P<title>[^|]+)\|\s*(?P<status>Active|Withdrawn|Superseded|Under revision)",
    re.IGNORECASE)


def parse_records(html: str) -> list[dict]:
    """Parse `IS <num>: <year> | <title> | <status>` fragments from a BIS page."""
    return [{"is_number": f"IS {m.group('num')}", "year": m.group("year"),
             "title_en": m.group("title").strip(), "status": m.group("status")}
            for m in RECORD_RE.finditer(html)]


def fetch(url: str, timeout_s: int = 20) -> str:
    """Live fetch: allowlisted hosts only. Disabled unless explicitly enabled."""
    from bis_assistant.config import load as load_config
    assert_allowlisted(url)
    if not load_config()["ingest"]["live_crawl_enabled"]:
        raise RuntimeError("live crawl disabled (config ingest.live_crawl_enabled=false)")
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "BIS-Assistant-KBbot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:  # noqa: S310 (allowlisted)
        return r.read().decode("utf-8", "replace")


def snapshot_raw(conn: sqlite3.Connection, url: str, raw: str, note: str = "") -> int:
    from bis_assistant import kb_store
    assert_allowlisted(url)
    snap = kb_store.new_snapshot(conn, f"crawl:{url}", note)
    conn.execute("CREATE TABLE IF NOT EXISTS raw_pages(snapshot_id INTEGER, url TEXT, raw TEXT)",
                 )
    conn.execute("INSERT INTO raw_pages VALUES (?,?,?)", (snap, url, raw))
    conn.commit()
    return snap


def diff_against_kb(conn: sqlite3.Connection, snapshot_id: int,
                    records: list[dict]) -> list[dict]:
    """Compare parsed records with published KB. Returns change dicts (also queued)."""
    from bis_assistant import kb_store
    current = {s["is_number"]: s for s in kb_store.load_standards(conn)}
    changes = []
    for rec in records:
        cur = current.pop(rec["is_number"], None)
        if cur is None:
            changes.append({"change_type": "added", **rec})
        elif (cur["year"] != rec["year"] or cur["title_en"] != rec["title_en"]
              or cur["status"] != rec["status"]):
            changes.append({"change_type": "changed", "was": {
                "year": cur["year"], "title_en": cur["title_en"],
                "status": cur["status"]}, **rec})
    for is_no, cur in current.items():
        if is_no == "IS 0000-DEMO":
            continue  # local test row, never diffed
        changes.append({"change_type": "missing-upstream", "is_number": is_no,
                        "year": cur["year"], "title_en": cur["title_en"],
                        "status": cur["status"]})
    for ch in changes:
        conn.execute("INSERT INTO pending_diffs(snapshot_id, change_type, is_number, details_json)"
                     " VALUES (?,?,?,?)",
                     (snapshot_id, ch["change_type"], ch["is_number"], json.dumps(ch)))
    conn.commit()
    return changes
