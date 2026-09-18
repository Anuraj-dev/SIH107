"""Manifest parsing/joining + corpus import (pure functions; script is a thin CLI).

Mapping rules:
- Each Files/*.txt maps via conversion_manifest `sourcePdfFilename` to a
  files.ndjson record (basename match). All 359 ship with a match; anything
  without a match is PRESERVED with empty provenance (never dropped).
- files.ndjson `sourceStandardId` joins to standards_metadata `standardId`
  (title/department/committee) and to standard_documents `standardId`
  (gazette/product_manual/... provenance for doc_type).
- The 24k standards_metadata rows go to `catalogue_standards`, deduped by
  standardId (part/section designations stay distinct rows).
- Duplicate TXT imports are idempotent on source_file (re-import replaces
  that document's chunks).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .chunking import chunk_text, clean_text, normalize_for_dedup
from .rag_store import connect_rag, counts, now

IS_IN_TEXT_RE = re.compile(r"IS\s*\d[\d/\-()A-Za-z ]{0,40}:\d{4}")


def load_ndjson(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _doc_type_for(source_ref: str, source_pdf: str, docs_entry: dict | None) -> tuple[str, str]:
    """Return (doc_type, category)."""
    blob = f"{source_ref} {source_pdf}".lower()
    if "product_manual" in blob or "standard_product_manual" in blob:
        return "product_manual", "product_manual"
    if "corrigend" in blob or "amendment" in blob:
        return "corrigendum", "gazette"
    if "gazett" in blob or re.match(r"^(\d+_.*|gf_.*)\.pdf$", os.path.basename(blob)):
        # gazette notifications (both numeric schedules and gf_ legacy files)
        return "gazette", "gazette"
    # Fall back to provenance: which section of standard_documents is populated
    if docs_entry:
        for key in ("product_manual", "gazette", "corrigendum", "standard_format", "summary"):
            sec = docs_entry.get(key)
            if isinstance(sec, dict) and sec.get("data"):
                data = sec["data"]
                if isinstance(data, dict):
                    det = data.get("product_manuals_details") or data.get("data")
                    if det:
                        return ("product_manual", "product_manual") if key == "product_manual" \
                            else (key, key)
                elif isinstance(data, list) and data:
                    return (key, key)
    return "gazette", "gazette"


def build_manifest_index(corpus_dir: Path) -> dict:
    """Load all manifests; return join dictionaries (pure, testable)."""
    corpus_dir = Path(corpus_dir)
    data_dir = corpus_dir / "data"
    standards = load_ndjson(data_dir / "standards_metadata.ndjson")
    files = load_ndjson(data_dir / "files.ndjson")
    docs = load_ndjson(data_dir / "standard_documents.ndjson")
    conv = json.loads((corpus_dir / "conversion_manifest.json").read_text(encoding="utf-8"))
    try:
        corpus_manifest = json.loads(
            (corpus_dir / "bis_corpus_manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        corpus_manifest = {}

    standards_by_id = {r.get("standardId"): r for r in standards if r.get("standardId") is not None}
    files_by_pdf: dict[str, dict] = {}
    for r in files:
        for key in ("path", "sourceRef"):
            base = os.path.basename(str(r.get(key) or ""))
            if base and base not in files_by_pdf:
                files_by_pdf[base] = r
    docs_by_id = {r.get("standardId"): r for r in docs if r.get("standardId") is not None}
    conv_by_txt = {r.get("text", "").replace("\\", "/"): r for r in conv.get("records", [])}
    # also index by bare filename for convenience
    for r in conv.get("records", []):
        conv_by_txt.setdefault(os.path.basename(r.get("text", "")), r)
    return {
        "standards": standards,
        "files": files,
        "docs": docs,
        "conversion": conv,
        "corpus_manifest": corpus_manifest,
        "standards_by_id": standards_by_id,
        "files_by_pdf": files_by_pdf,
        "docs_by_id": docs_by_id,
        "conv_by_txt": conv_by_txt,
    }


def map_txt_to_metadata(txt_rel: str, index: dict) -> dict:
    """Join one TXT file to its manifest rows. Never drops: unmatched -> blanks."""
    base = os.path.basename(txt_rel)
    conv = index["conv_by_txt"].get(txt_rel) or index["conv_by_txt"].get(base) or {}
    source_pdf = conv.get("sourcePdfFilename", base.replace(".txt", ".pdf"))
    frec = index["files_by_pdf"].get(source_pdf, {})
    sid = frec.get("sourceStandardId")
    snum = frec.get("sourceStandardNumber", "")
    srec = index["standards_by_id"].get(sid, {})
    drec = index["docs_by_id"].get(sid)
    if not snum:
        snum = srec.get("standardNumber", "") or (drec.get("standardNumber", "") if drec else "")
    title = srec.get("standardName", "") or srec.get("standardLabel", "") or snum
    doc_type, category = _doc_type_for(
        str(frec.get("sourceRef", "")), source_pdf, drec if isinstance(drec, dict) else None)
    return {
        "source_file": txt_rel if txt_rel.startswith("Files/") else f"Files/{base}",
        "standard_id": sid,
        "standard_number": snum or "",
        "title": title or "",
        "department": srec.get("departmentName", ""),
        "committee": srec.get("sectionalCommitteeName", ""),
        "doc_type": doc_type,
        "category": category,
        "source_url": frec.get("url", ""),
        "source_pdf": source_pdf,
        "source_ref": frec.get("sourceRef", ""),
        "extraction_method": conv.get("method", ""),
        "translation": conv.get("translation", ""),
        "matched_file": bool(frec),
        "matched_standard": bool(srec),
    }


def import_corpus(corpus_dir: str | Path, db_path: str | Path,
                  batch_commit: bool = True) -> dict:
    """Full import: catalogue + documents + chunks + FTS. Returns stats."""
    corpus_dir = Path(corpus_dir)
    files_dir = corpus_dir / "Files"
    index = build_manifest_index(corpus_dir)
    conn = connect_rag(db_path)
    stats = {"documents": 0, "chunks": 0, "catalogue": 0,
             "matched": 0, "unmatched": 0, "skipped_empty": 0}
    try:
        # 1. Catalogue (dedupe by standardId; keep part/section rows distinct)
        snap_rows = 0
        for r in index["standards"]:
            sid = r.get("standardId")
            if sid is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO catalogue_standards(standard_id, standard_number,"
                " standard_label, standard_name, department, committee, type_name, published_on)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (sid, r.get("standardNumber", ""), r.get("standardLabel", ""),
                 r.get("standardName", ""), r.get("departmentName", ""),
                 r.get("sectionalCommitteeName", ""), r.get("typeOfStandardName", ""),
                 r.get("publishedOn", "")))
            snap_rows += 1
        stats["catalogue"] = snap_rows

        # 2. Documents + chunks
        txt_files = sorted(p for p in files_dir.glob("*.txt") if p.is_file())
        for txt_path in txt_files:
            txt_rel = f"Files/{txt_path.name}"
            meta = map_txt_to_metadata(txt_rel, index)
            try:
                raw = txt_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stats["skipped_empty"] += 1
                continue
            if not raw.strip():
                stats["skipped_empty"] += 1
                continue
            cleaned = clean_text(raw)
            if meta["matched_file"]:
                stats["matched"] += 1
            else:
                stats["unmatched"] += 1
            # Idempotent: replace existing doc + chunks for this source_file
            old = conn.execute("SELECT id FROM corpus_documents WHERE source_file=?",
                               (meta["source_file"],)).fetchone()
            if old:
                conn.execute("DELETE FROM corpus_chunks WHERE doc_id=?", (old["id"],))
                conn.execute("DELETE FROM corpus_documents WHERE id=?", (old["id"],))
            cur = conn.execute(
                "INSERT INTO corpus_documents(source_file, standard_id, standard_number,"
                " title, department, committee, doc_type, category, source_url, source_pdf,"
                " source_ref, extraction_method, translation, chars, raw_text, cleaned_text,"
                " imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (meta["source_file"], meta["standard_id"], meta["standard_number"],
                 meta["title"], meta["department"], meta["committee"], meta["doc_type"],
                 meta["category"], meta["source_url"], meta["source_pdf"], meta["source_ref"],
                 meta["extraction_method"], meta["translation"], len(raw),
                 raw, cleaned, now()))
            doc_id = cur.lastrowid
            chunks = chunk_text(cleaned) or [{"chunk_text": cleaned[:2000], "heading": "",
                                              "char_start": 0, "char_end": len(cleaned),
                                              "token_count": 0}]
            # In-doc dedup on normalised chunk text
            seen: set[str] = set()
            ci = 0
            for ch in chunks:
                norm = normalize_for_dedup(ch["chunk_text"])
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                conn.execute(
                    "INSERT INTO corpus_chunks(doc_id, chunk_index, chunk_text, heading,"
                    " char_start, char_end, token_count, standard_number, doc_type, source_url)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (doc_id, ci, ch["chunk_text"], ch.get("heading", ""),
                     ch.get("char_start", 0), ch.get("char_end", 0),
                     ch.get("token_count", 0), meta["standard_number"], meta["doc_type"],
                     meta["source_url"]))
                ci += 1
            stats["documents"] += 1
            stats["chunks"] += ci
        conn.commit()
        stats.update(counts(conn))
        return stats
    finally:
        conn.close()
