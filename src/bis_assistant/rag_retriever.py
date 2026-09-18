"""Hybrid retrieval over corpus_chunks: exact IS boost + FTS5/BM25 + semantic.

Fuse lexical, semantic and metadata rankings; return evidence chunks with
source metadata for answer generation and UI display.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from . import rag_embeddings as emb

IS_RE = re.compile(r"IS\s*(\d+(?:\s*[-/]\s*\d+)?)", re.IGNORECASE)
IS_FULL_RE = re.compile(
    r"IS\s*(\d+)\s*(?:\(\s*Part\s*([^):/]+?)?\s*(?:/\s*Sec(?:tion|\.)?\s*([^):]+?))?\s*\:?)?"
    r"\s*:?\s*(\d{4})?", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_FTS_RESERVED = re.compile(r"[\":*^()]")


def extract_is_numbers(query: str) -> list[str]:
    """Raw IS designations found in text, e.g. ['IS 101 (Part 2/Sec 6):2026']."""
    out = []
    for m in re.finditer(
            r"IS\s*\d+(?:\s*\([^)]*\))?\s*(?::\s*\d{4})?", query, re.IGNORECASE):
        out.append(re.sub(r"\s+", " ", m.group(0).strip()))
    return out


def _digits(s: str) -> str:
    m = re.search(r"\d+", s or "")
    return m.group(0) if m else ""


def _normalize_is(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").upper().replace("–", "-").replace("—", "-"))
    s = re.sub(r"\s*:\s*", ":", s)
    s = re.sub(r"\(\s*", "(", s)
    s = re.sub(r"\s*\)", ")", s)
    return s.strip()


def _fts_query(query: str) -> str:
    toks = [t for t in _TOKEN_RE.findall(query.lower()) if len(t) > 1]
    # keep IS digits glued: 'IS 101' -> 'IS101' token variant too
    extra = []
    for m in IS_RE.finditer(query):
        extra.append("IS" + re.sub(r"\D", "", m.group(0)))
    toks = toks + extra
    # de-dup, cap length, quote phrases safely
    seen, out = set(), []
    for t in toks:
        t = _FTS_RESERVED.sub("", t).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(f'"{t}"')
        if len(out) >= 12:
            break
    return " OR ".join(out) if out else '""'


def _token_overlap_score(query: str, text: str) -> float:
    q = set(t for t in _TOKEN_RE.findall(query.lower()) if len(t) > 2)
    d = set(t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2)
    if not q or not d:
        return 0.0
    return len(q & d) / (len(q) ** 0.5)


def search_rag(query: str, top_k: int = 5,
               db_path: str | Path | None = None,
               lexical_weight: float = 1.0, semantic_weight: float = 0.3,
               exact_boost: float = 50.0, semantic: bool = True,
               embedding_model: str = "") -> list[dict]:
    """Hybrid search. Empty list when DB missing/empty (never raises)."""
    from .rag_config import load_rag_config
    cfg = load_rag_config()
    db_path = str(db_path or cfg["db_path"])
    top_k = int(top_k or cfg["top_k"])
    if not os.path.exists(db_path):
        return []
    q = (query or "").strip()
    if not q:
        return []
    q_is = extract_is_numbers(q)
    q_digits = {_digits(x) for x in q_is if _digits(x)}
    q_norm = {_normalize_is(x) for x in q_is}
    fts_q = _fts_query(q)
    over_fetch = max(top_k * 6, 20)

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    try:
        # Does the corpus exist?
        try:
            n = conn.execute("SELECT COUNT(*) c FROM corpus_chunks").fetchone()["c"]
        except Exception:
            return []
        if not n:
            return []
        rows: list[dict] = []
        used_fts = False
        try:
            cur = conn.execute(
                "SELECT c.id, c.doc_id, c.chunk_index, c.chunk_text, c.heading,"
                " c.char_start, c.char_end, c.token_count, c.standard_number,"
                " c.doc_type, c.source_url, bm25(corpus_chunks_fts) AS rank"
                " FROM corpus_chunks_fts JOIN corpus_chunks c ON c.id = corpus_chunks_fts.rowid"
                " WHERE corpus_chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_q, over_fetch))
            for r in cur.fetchall():
                rows.append(dict(r))
            used_fts = True
        except Exception:
            rows = []
        if not rows:
            # LIKE fallback (no FTS5 or no MATCH hits): token-OR scan, capped.
            toks = [t for t in _TOKEN_RE.findall(q.lower()) if len(t) > 2][:8]
            if not toks:
                return []
            where = " OR ".join(["chunk_text LIKE ?"] * len(toks))
            params = [f"%{t}%" for t in toks]
            try:
                cur = conn.execute(
                    f"SELECT c.*, 0.0 AS rank FROM corpus_chunks c WHERE {where} LIMIT ?",
                    (*params, over_fetch))
                for r in cur.fetchall():
                    rows.append(dict(r))
            except Exception:
                return []
        # Enrich with document metadata
        doc_cache: dict = {}
        scored: list[dict] = []
        qvec = None
        if semantic:
            try:
                _, qvec = emb.embed_query(q, embedding_model or cfg.get("embedding_model", ""))
            except Exception:
                qvec = None
        for r in rows:
            doc_id = r.get("doc_id")
            if doc_id not in doc_cache:
                try:
                    d = conn.execute(
                        "SELECT * FROM corpus_documents WHERE id=?", (doc_id,)).fetchone()
                    doc_cache[doc_id] = dict(d) if d else {}
                except Exception:
                    doc_cache[doc_id] = {}
            d = doc_cache[doc_id]
            std_num = r.get("standard_number") or d.get("standard_number", "")
            # Exact IS boost: digit match strong; full designation match stronger
            boost = 0.0
            if q_digits and _digits(std_num) in q_digits:
                boost = exact_boost
                if q_norm and _normalize_is(std_num) in q_norm:
                    boost *= 1.5
            # Lexical: convert FTS rank (negative, closer to 0 = better) to positive
            rank = r.get("rank", 0.0) or 0.0
            try:
                lex = -float(rank)
            except (TypeError, ValueError):
                lex = 0.0
            if not used_fts:
                lex = _token_overlap_score(q, r.get("chunk_text", "")) * 10.0
            # Semantic channel
            sem = 0.0
            if semantic:
                try:
                    sem = emb.semantic_score(
                        q, (r.get("chunk_text", "")[:2000]),
                        embedding_model or cfg.get("embedding_model", ""), _qvec=qvec)
                except Exception:
                    sem = 0.0
                # blend hashed-cosine with plain overlap for stability
                sem = 0.5 * sem + 0.5 * min(1.0, _token_overlap_score(q, r.get("chunk_text", "")))
            fused = lexical_weight * lex + boost + semantic_weight * sem * 10.0
            scored.append({
                "chunk_id": r.get("id"),
                "doc_id": doc_id,
                "chunk_index": r.get("chunk_index", 0),
                "chunk_text": r.get("chunk_text", ""),
                "heading": r.get("heading", ""),
                "char_start": r.get("char_start", 0),
                "char_end": r.get("char_end", 0),
                "standard_number": std_num,
                "title": d.get("title", ""),
                "department": d.get("department", ""),
                "committee": d.get("committee", ""),
                "doc_type": r.get("doc_type") or d.get("doc_type", ""),
                "source_url": r.get("source_url") or d.get("source_url", ""),
                "source_file": d.get("source_file", ""),
                "extraction_method": d.get("extraction_method", ""),
                "score": fused,
                "lexical": lex,
                "semantic": sem,
                "exact_boost": boost,
                "exact_match": boost > 0,
            })
        scored.sort(key=lambda x: -x["score"])
        # Prefer exact matches first regardless of fusion noise
        exact = [s for s in scored if s["exact_match"]]
        rest = [s for s in scored if not s["exact_match"]]
        ordered = (exact + rest)[:top_k] if exact else scored[:top_k]
        return ordered
    finally:
        try:
            conn.close()
        except Exception:
            pass
