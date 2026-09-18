"""SQLite store for the BIS RAG corpus (separate DB from the curated KB).

Tables:
  corpus_documents: one row per TXT file (raw text kept for traceability).
  corpus_chunks: retrieval-ready chunks with heading/offsets + denormalised
    standard_number/doc_type/source_url for FTS filtering and display.
  catalogue_standards: the ~24k BIS catalogue rows (dedupe by standardId;
    part/section designations stay distinct rows).
  corpus_chunks_fts: FTS5 index over chunk_text + standard_number + doc_type
    + heading.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_file TEXT UNIQUE NOT NULL,
  standard_id INTEGER,
  standard_number TEXT DEFAULT '',
  title TEXT DEFAULT '',
  department TEXT DEFAULT '',
  committee TEXT DEFAULT '',
  doc_type TEXT DEFAULT '',
  category TEXT DEFAULT '',
  source_url TEXT DEFAULT '',
  source_pdf TEXT DEFAULT '',
  source_ref TEXT DEFAULT '',
  extraction_method TEXT DEFAULT '',
  translation TEXT DEFAULT '',
  chars INTEGER DEFAULT 0,
  raw_text TEXT DEFAULT '',
  cleaned_text TEXT DEFAULT '',
  imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corpus_chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES corpus_documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_text TEXT NOT NULL,
  heading TEXT DEFAULT '',
  char_start INTEGER DEFAULT 0,
  char_end INTEGER DEFAULT 0,
  token_count INTEGER DEFAULT 0,
  standard_number TEXT DEFAULT '',
  doc_type TEXT DEFAULT '',
  source_url TEXT DEFAULT '',
  UNIQUE(doc_id, chunk_index)
);
CREATE TABLE IF NOT EXISTS catalogue_standards(
  standard_id INTEGER PRIMARY KEY,
  standard_number TEXT NOT NULL,
  standard_label TEXT DEFAULT '',
  standard_name TEXT DEFAULT '',
  department TEXT DEFAULT '',
  committee TEXT DEFAULT '',
  type_name TEXT DEFAULT '',
  published_on TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON corpus_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_stdnum ON corpus_chunks(standard_number);
CREATE INDEX IF NOT EXISTS idx_docs_stdnum ON corpus_documents(standard_number);
CREATE INDEX IF NOT EXISTS idx_catalogue_number ON catalogue_standards(standard_number);
"""

CATALOGUE_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS catalogue_fts USING fts5(
  standard_number, standard_name, department, committee, type_name,
  content='catalogue_standards', content_rowid='standard_id', tokenize='porter');
CREATE TRIGGER IF NOT EXISTS catalogue_ai AFTER INSERT ON catalogue_standards BEGIN
  INSERT INTO catalogue_fts(rowid, standard_number, standard_name, department, committee, type_name)
  VALUES (new.standard_id, new.standard_number, new.standard_name,
          new.department, new.committee, new.type_name);
END;
CREATE TRIGGER IF NOT EXISTS catalogue_ad AFTER DELETE ON catalogue_standards BEGIN
  INSERT INTO catalogue_fts(catalogue_fts, rowid, standard_number, standard_name,
          department, committee, type_name)
  VALUES ('delete', old.standard_id, old.standard_number, old.standard_name,
          old.department, old.committee, old.type_name);
END;
CREATE TRIGGER IF NOT EXISTS catalogue_au AFTER UPDATE ON catalogue_standards BEGIN
  INSERT INTO catalogue_fts(catalogue_fts, rowid, standard_number, standard_name,
          department, committee, type_name)
  VALUES ('delete', old.standard_id, old.standard_number, old.standard_name,
          old.department, old.committee, old.type_name);
  INSERT INTO catalogue_fts(rowid, standard_number, standard_name, department, committee, type_name)
  VALUES (new.standard_id, new.standard_number, new.standard_name,
          new.department, new.committee, new.type_name);
END;
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS corpus_chunks_fts USING fts5(
  chunk_text, standard_number, doc_type, heading,
  content='corpus_chunks', content_rowid='id', tokenize='porter');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON corpus_chunks BEGIN
  INSERT INTO corpus_chunks_fts(rowid, chunk_text, standard_number, doc_type, heading)
  VALUES (new.id, new.chunk_text, new.standard_number, new.doc_type, new.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON corpus_chunks BEGIN
  INSERT INTO corpus_chunks_fts(corpus_chunks_fts, rowid, chunk_text, standard_number, doc_type, heading)
  VALUES ('delete', old.id, old.chunk_text, old.standard_number, old.doc_type, old.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON corpus_chunks BEGIN
  INSERT INTO corpus_chunks_fts(corpus_chunks_fts, rowid, chunk_text, standard_number, doc_type, heading)
  VALUES ('delete', old.id, old.chunk_text, old.standard_number, old.doc_type, old.heading);
  INSERT INTO corpus_chunks_fts(rowid, chunk_text, standard_number, doc_type, heading)
  VALUES (new.id, new.chunk_text, new.standard_number, new.doc_type, new.heading);
END;
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_rag(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(RAG_SCHEMA)
    try:
        conn.executescript(FTS_SCHEMA)
    except sqlite3.OperationalError:
        # FTS5 unavailable (minimal builds): lexical search falls back to LIKE.
        pass
    try:
        conn.executescript(CATALOGUE_FTS_SCHEMA)
        _ensure_catalogue_fts(conn)
    except sqlite3.OperationalError:
        pass
    # Lightweight migration: older DBs may miss columns.
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(corpus_documents)").fetchall()}
        for col in ("cleaned_text", "category", "source_ref"):
            if col not in cols:
                conn.execute(f"ALTER TABLE corpus_documents ADD COLUMN {col} TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_catalogue_fts(conn: sqlite3.Connection) -> None:
    """Backfill + self-heal the catalogue FTS index (issue #4 P1-10).

    One-time backfill for DBs imported before catalogue_fts existed, plus
    a MATCH probe: a populated-but-unsearchable index (observed once on a
    migrated DB) is rebuilt from the content table. DELETE+rebuild is
    idempotent, so re-running is always safe.
    """
    import re as _re
    try:
        n_cat = conn.execute("SELECT COUNT(*) c FROM catalogue_standards").fetchone()["c"]
    except Exception:
        return
    if not n_cat:
        return
    try:
        n_fts = conn.execute("SELECT COUNT(*) c FROM catalogue_fts").fetchone()["c"]
    except Exception:
        return
    healthy = False
    if n_fts == n_cat:
        try:
            row = conn.execute(
                "SELECT standard_name FROM catalogue_standards"
                " WHERE standard_name <> '' LIMIT 1").fetchone()
            toks = _re.findall(r"[a-z0-9]{3,}", (row[0] if row else "").lower())
            if toks:
                probe = conn.execute(
                    "SELECT rowid FROM catalogue_fts"
                    " WHERE catalogue_fts MATCH ? LIMIT 1", (f'"{toks[0]}"',)
                ).fetchone()
                healthy = probe is not None
        except Exception:
            healthy = False
    if not healthy:
        conn.execute("DELETE FROM catalogue_fts")
        conn.execute("INSERT INTO catalogue_fts(catalogue_fts) VALUES('rebuild')")
        conn.commit()


def has_fts(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='corpus_chunks_fts'").fetchone()
        return row is not None
    except Exception:
        return False


def counts(conn: sqlite3.Connection) -> dict:
    out = {}
    for t in ("corpus_documents", "corpus_chunks", "catalogue_standards"):
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        except Exception:
            out[t] = 0
    out["fts"] = has_fts(conn)
    return out
