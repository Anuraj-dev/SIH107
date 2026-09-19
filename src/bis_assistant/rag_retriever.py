"""Hybrid retrieval: exact IS boost, FTS5/BM25, optional dense search and reranking.

Fuse lexical and dense ranks; return source-bearing evidence for generation.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from . import rag_embeddings as emb

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_FTS_RESERVED = re.compile(r"[\":*^()]")


def extract_is_numbers(query: str) -> list[str]:
    """Raw IS designations found in text, e.g. ['IS 101 (Part 2/Sec 6):2026'].

    Hyphenated forms (`IS-10500`) are accepted; use
    ``retriever.normalize_is_ref`` for canonical comparison.
    """
    out = []
    for m in re.finditer(
            r"IS\s*-?\s*\d+(?:\s*\([^)]*\))?\s*(?::\s*\d{4})?", query, re.IGNORECASE):
        out.append(re.sub(r"\s+", " ", m.group(0).strip()))
    return out


def _parse_is_parts(ref: str) -> tuple[str, str, str]:
    """Split a designation into (base, part, sec), e.g. IS 101 (Part 2/Sec 6).

    Handles `IS 302-1` hyphen parts and `IS/IEC ...` prefixes. Year is
    ignored: retrieval matches designations, not editions.
    """
    n = _normalize_is(ref)
    base, part, sec = "", "", ""
    m = re.search(r"IS(?:/[A-Z]+)?\s*(\d+)", n)
    if m:
        base = m.group(1)
    else:
        return base, part, sec
    mp = re.search(r"PART\s*([A-Z0-9]+)", n)
    if mp:
        part = mp.group(1)
    else:
        mh = re.search(r"IS(?:/[A-Z]+)?\s*\d+\s*-\s*([A-Z0-9]+)", n)
        if mh:
            part = mh.group(1)
    ms = re.search(r"SEC(?:TION|\.)?\s*([A-Z0-9]+)", n)
    if ms:
        sec = ms.group(1)
    return base, part, sec


def _is_boost(std_num: str, query_refs: list[str], exact_boost: float) -> tuple[float, bool]:
    """Tiered IS boost (issue #4 P1-7): full designation > base+part > base.

    Any tier counts as an exact match (preserves base-query diversion);
    the multiplier separates `IS 101 (Part 2/Sec 6)` from its siblings
    instead of boosting every Part/Sec variant equally.
    """
    if not query_refs or not std_num:
        return 0.0, False
    sb, sp, ss = _parse_is_parts(std_num)
    if not sb:
        return 0.0, False
    best = 0.0
    for qr in query_refs:
        qb, qp, qs = _parse_is_parts(qr)
        if not qb or qb != sb:
            continue
        if qp and qp == sp and (not qs or not ss or qs == ss):
            best = max(best, exact_boost * 1.5)  # full designation
        elif qp and qp == sp:
            best = max(best, exact_boost * 1.25)  # same part, other section
        elif not qp:
            # Query names the base only: full marks when the doc is also
            # part-less, base marks when it refines into parts/sections.
            best = max(best, exact_boost * 1.5 if not sp else exact_boost)
        else:
            best = max(best, exact_boost * 0.5)  # same base, other part
    return (best, True) if best > 0 else (0.0, False)


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
    for m in extract_is_numbers(query):
        extra.append("IS" + re.sub(r"\D", "", m))
    # FTS tokenizes punctuation in corpus designations (`IS 14543 : 2016`)
    # into separate words. Search the standard number as an exact phrase so
    # common terms such as `packing` cannot bury the requested designation.
    exact_numbers = [re.search(r"\d+", ref).group(0) for ref in extract_is_numbers(query)]
    exact_clause = " OR ".join(f'"{n}"' for n in exact_numbers if n)
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
    ordinary = " OR ".join(out)
    return f"({ordinary}) OR ({exact_clause})" if exact_clause and ordinary else (
        exact_clause or ordinary or '""')


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
               embedding_model: str = "",
               _conn: sqlite3.Connection | None = None) -> list[dict]:
    """Hybrid search. Empty list when DB missing/empty (never raises).

    Pass ``_conn`` to reuse one connection per request (issue #4 P1-10);
    caller-owned connections are never closed here.
    """
    from .rag_config import load_rag_config
    cfg = load_rag_config()
    db_path = str(db_path or cfg["db_path"])
    top_k = max(1, int(top_k or cfg["top_k"]))
    if not os.path.exists(db_path):
        return []
    q = (query or "").strip()
    if not q:
        return []
    q_is = extract_is_numbers(q)
    fts_q = _fts_query(q)
    candidate_limit = max(top_k * 6, 20)

    own_conn = _conn is None
    if _conn is not None:
        conn = _conn
    else:
        if not os.path.exists(db_path):
            return []
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
        lexical_rows: list[dict] = []
        used_fts = False
        try:
            cur = conn.execute(
                "SELECT c.id, c.doc_id, c.chunk_index, c.chunk_text, c.heading,"
                " c.char_start, c.char_end, c.token_count, c.standard_number,"
                " c.doc_type, c.source_url, bm25(corpus_chunks_fts) AS rank"
                " FROM corpus_chunks_fts JOIN corpus_chunks c ON c.id = corpus_chunks_fts.rowid"
                " WHERE corpus_chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_q, candidate_limit))
            for r in cur.fetchall():
                lexical_rows.append(dict(r))
            used_fts = True
        except Exception:
            pass

        model_name = embedding_model or cfg.get("embedding_model", "")
        dense_hits = (emb.dense_search(db_path, q, model_name, candidate_limit)
                      if semantic and model_name else [])
        if semantic and model_name and not dense_hits and lexical_rows:
            model = emb.get_model(model_name)
            if model is not None:
                try:
                    query_vector = model.encode([q], normalize_embeddings=True)[0]
                    texts = [row.get("chunk_text", "")[:2000] for row in lexical_rows]
                    vectors = model.encode(texts, normalize_embeddings=True)
                    dense_hits = sorted(
                        [(int(row["id"]), emb.cosine(query_vector, vector))
                         for row, vector in zip(lexical_rows, vectors, strict=True)],
                        key=lambda item: -item[1],
                    )
                except Exception:
                    dense_hits = []
        dense_scores = dict(dense_hits)
        dense_ranks = {chunk_id: rank for rank, (chunk_id, _) in enumerate(dense_hits, 1)}
        rows_by_id = {int(row["id"]): row for row in lexical_rows}
        missing_ids = [chunk_id for chunk_id, _ in dense_hits if chunk_id not in rows_by_id]
        if missing_ids:
            placeholders = ",".join("?" for _ in missing_ids)
            for row in conn.execute(
                    f"SELECT * FROM corpus_chunks WHERE id IN ({placeholders})", missing_ids):
                item = dict(row)
                item["rank"] = 0.0
                rows_by_id[int(item["id"])] = item

        if not rows_by_id:
            # FTS5 can be missing or have no lexical hit. Keep a small LIKE
            # fallback for minimal SQLite builds and empty dense indexes.
            toks = [t for t in _TOKEN_RE.findall(q.lower()) if len(t) > 2][:8]
            if not toks:
                return []
            where = " OR ".join(["chunk_text LIKE ?"] * len(toks))
            params = [f"%{t}%" for t in toks]
            try:
                cur = conn.execute(
                    f"SELECT c.*, 0.0 AS rank FROM corpus_chunks c WHERE {where} LIMIT ?",
                    (*params, candidate_limit))
                lexical_rows = [dict(row) for row in cur.fetchall()]
                rows_by_id.update({int(row["id"]): row for row in lexical_rows})
                used_fts = False
            except Exception:
                return []

        lexical_scores = {}
        for row in lexical_rows:
            try:
                value = -float(row.get("rank", 0.0) or 0.0) if used_fts else 0.0
            except (TypeError, ValueError):
                value = 0.0
            if not used_fts:
                value = _token_overlap_score(q, row.get("chunk_text", "")) * 10.0
            lexical_scores[int(row["id"])] = value
        lexical_ranks = {
            chunk_id: rank for rank, (chunk_id, _) in enumerate(
                sorted(lexical_scores.items(), key=lambda item: -item[1]), 1)
        }

        # Enrich the union of lexical and dense candidates with source metadata.
        doc_cache: dict = {}
        scored: list[dict] = []
        for chunk_id, r in rows_by_id.items():
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
            # Tiered IS boost (P1-7): full designation > base+part > base.
            boost, is_exact = _is_boost(std_num, q_is, exact_boost)
            lex = lexical_scores.get(chunk_id, 0.0)
            sem = dense_scores.get(chunk_id, 0.0)
            fused = lexical_weight * lex + boost + semantic_weight * sem * 10.0
            rrf = (lexical_weight / (60 + lexical_ranks[chunk_id])
                   if chunk_id in lexical_ranks else 0.0)
            rrf += (semantic_weight / (60 + dense_ranks[chunk_id])
                    if chunk_id in dense_ranks else 0.0)
            scored.append({
                "chunk_id": chunk_id,
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
                "rrf_score": rrf,
                "exact_boost": boost,
                "exact_match": is_exact,
            })
        ordered = sorted(scored, key=lambda item: (
            not item["exact_match"], -item["rrf_score"], -item["score"]))

        rerank_model = cfg.get("reranker_model", "")
        pool = ordered[:candidate_limit]
        rerank_scores = emb.rerank_scores(
            q, [item["chunk_text"][:2000] for item in pool], rerank_model)
        if rerank_scores is not None:
            for item, score in zip(pool, rerank_scores, strict=True):
                item["rerank_score"] = score
            ordered = sorted(ordered, key=lambda item: (
                not item["exact_match"],
                -item.get("rerank_score", -1.0),
                -item["rrf_score"],
                -item["score"],
            ))
        return ordered[:top_k]
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass
