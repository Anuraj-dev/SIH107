"""Versioned KB store (SQLite). Schema per plan §2 (reviewed).

Deviation notes (documented, not silent):
- `standards` also carries `keywords_json` + `clarify_json` + `scheme_text` so the
  SQLite backend reproduces JSON-backend answers exactly (shadow-compare enforced).
- `section_ref`/`source_snippet` ship EMPTY in v1 -> verifier forbids clause numbers.
- `qco_status` ships 'unknown' -> requires human review before any compulsory claim.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
  source TEXT NOT NULL, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS standards(
  id INTEGER PRIMARY KEY AUTOINCREMENT, is_number TEXT NOT NULL, year TEXT DEFAULT '',
  title_en TEXT DEFAULT '', title_hi DEFAULT '', scope_en TEXT DEFAULT '',
  scope_hi TEXT DEFAULT '', status TEXT DEFAULT 'Active', scheme_key TEXT DEFAULT '',
  scheme_text TEXT DEFAULT '', source_url TEXT DEFAULT '', esale_url TEXT DEFAULT '',
  section_ref TEXT DEFAULT '', source_snippet TEXT DEFAULT '',
  qco_status TEXT DEFAULT 'unknown', qco_checked_at TEXT,
  keywords_json TEXT DEFAULT '[]', clarify_json TEXT DEFAULT '[]',
  captured_at TEXT NOT NULL, last_checked TEXT NOT NULL,
  supersedes TEXT DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
  snapshot_id INTEGER REFERENCES snapshots(id),
  department TEXT DEFAULT '', dept_code TEXT DEFAULT '', aspect TEXT DEFAULT '',
  equivalence TEXT DEFAULT '', pub_date TEXT DEFAULT '', detail_url TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS schemes(
  key TEXT PRIMARY KEY, name_en TEXT, name_hi TEXT, process_en_json TEXT,
  process_hi_json TEXT, apply_url TEXT, source_url TEXT, suitable_for TEXT,
  last_checked TEXT);
CREATE TABLE IF NOT EXISTS labs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, city TEXT, type TEXT,
  scope_note TEXT, source_url TEXT, last_checked TEXT, verified INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS glossary(term TEXT PRIMARY KEY, en TEXT, hi TEXT, source_url TEXT);
CREATE TABLE IF NOT EXISTS slots(
  is_number TEXT, key TEXT, q_en TEXT, q_hi TEXT, options_json TEXT, pattern TEXT,
  PRIMARY KEY (is_number, key));
CREATE TABLE IF NOT EXISTS info_pages(key TEXT PRIMARY KEY, title TEXT, url TEXT, last_checked TEXT);
CREATE TABLE IF NOT EXISTS pending_diffs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id INTEGER REFERENCES snapshots(id),
  change_type TEXT NOT NULL, is_number TEXT NOT NULL, details_json TEXT DEFAULT '{}',
  status TEXT DEFAULT 'pending', decided_at TEXT);
CREATE INDEX IF NOT EXISTS idx_standards_is_ver ON standards(is_number, version, id);
CREATE INDEX IF NOT EXISTS idx_diffs_status ON pending_diffs(status, change_type);
"""

KB_VERSION = "v2"

# Breadth columns added for DG-dashboard list metadata (v2). Existing v1
# databases are migrated on connect() via ALTER TABLE (additive, no rewrite).
BREADTH_COLUMNS = ("department", "dept_code", "aspect",
                   "equivalence", "pub_date", "detail_url")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Migrate v1 databases: add breadth columns if missing (additive).
    existing = {r["name"] for r in
                conn.execute("PRAGMA table_info(standards)").fetchall()}
    for col in BREADTH_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE standards ADD COLUMN {col} TEXT DEFAULT ''")
    conn.commit()
    return conn


def new_snapshot(conn: sqlite3.Connection, source: str, note: str = "") -> int:
    cur = conn.execute("INSERT INTO snapshots(created_at, source, note) VALUES (?,?,?)",
                       (now(), source, note))
    conn.commit()
    return cur.lastrowid


def upsert_standard(conn: sqlite3.Connection, row: dict, snapshot_id: int) -> None:
    full = {"department": "", "dept_code": "", "aspect": "", "equivalence": "",
            "pub_date": "", "detail_url": "", **row, "snapshot_id": snapshot_id}
    conn.execute(
        """INSERT INTO standards(is_number, year, title_en, title_hi, scope_en, scope_hi,
           status, scheme_key, scheme_text, source_url, esale_url, section_ref,
           source_snippet, qco_status, qco_checked_at, keywords_json, clarify_json,
           captured_at, last_checked, supersedes, version, snapshot_id,
           department, dept_code, aspect, equivalence, pub_date, detail_url)
           VALUES (:is_number, :year, :title_en, :title_hi, :scope_en, :scope_hi,
           :status, :scheme_key, :scheme_text, :source_url, :esale_url, :section_ref,
           :source_snippet, :qco_status, :qco_checked_at, :keywords_json, :clarify_json,
           :captured_at, :last_checked, :supersedes, :version, :snapshot_id,
           :department, :dept_code, :aspect, :equivalence, :pub_date, :detail_url)""",
        full)
    conn.commit()


def _row_to_std(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("rn", None)  # window-query helper column, not a standard field
    d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
    d["category_keywords"] = d.pop("keywords")
    d["clarify"] = json.loads(d.pop("clarify_json") or "[]")
    d["scheme"] = d.pop("scheme_text")
    return d


def load_standards(conn: sqlite3.Connection) -> list[dict]:
    """Latest version per IS number (max version, then max id).

    Single-pass window query + index: correlated-subquery form is O(n^2)
    and collapses at breadth scale (~20k rows).
    """
    rows = conn.execute(
        """SELECT * FROM (SELECT *, ROW_NUMBER() OVER (
              PARTITION BY is_number ORDER BY version DESC, id DESC) AS rn
            FROM standards) WHERE rn = 1""").fetchall()
    return [_row_to_std(r) for r in rows]


def load_schemes(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM schemes").fetchall():
        d = dict(r)
        out.append({"key": d["key"], "name_en": d["name_en"], "name_hi": d["name_hi"],
                    "process_en": json.loads(d["process_en_json"]),
                    "process_hi": json.loads(d["process_hi_json"]),
                    "apply_at": d["apply_url"], "source_url": d["source_url"],
                    "suitable_for": d["suitable_for"]})
    return out


def load_labs(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT * FROM labs").fetchall()
    lims = conn.execute("SELECT url FROM info_pages WHERE key='lims'").fetchone()
    return {"samples": [{"name": r["name"], "city": r["city"], "type": r["type"],
                         "scope": r["scope_note"]} for r in rows],
            "lims_search": lims["url"] if lims else ""}


def load_glossary(conn: sqlite3.Connection) -> list[dict]:
    return [{"term": r["term"], "en": r["en"], "hi": r["hi"]}
            for r in conn.execute("SELECT * FROM glossary").fetchall()]


def load_slots(conn: sqlite3.Connection) -> dict:
    out: dict[str, list[dict]] = {}
    for r in conn.execute("SELECT * FROM slots").fetchall():
        out.setdefault(r["is_number"], []).append(
            {"key": r["key"], "q_en": r["q_en"], "q_hi": r["q_hi"],
             "options": json.loads(r["options_json"] or "[]"), "pattern": r["pattern"]})
    return out
