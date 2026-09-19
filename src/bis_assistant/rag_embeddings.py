"""Optional local embedding and cross-encoder models for corpus retrieval.

The SQLite/FTS path stays dependency-free. Configuring a model enables dense
candidate search or reranking; both models load lazily and fail back to FTS.
"""
from __future__ import annotations

import logging
import math
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("bis.rag")


@lru_cache(maxsize=2)
def _embedding_model(name: str):
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(name)
    except Exception as exc:
        log.warning("dense retrieval model unavailable; using lexical search",
                    extra={"ctx": {"model": name, "reason": type(exc).__name__}})
        return None


def get_model(name: str):
    """Load a sentence-transformers model once, on first use."""
    return _embedding_model(name) if name else None


def cosine(left, right) -> float:
    return float(sum(float(a) * float(b) for a, b in zip(left, right)))


def semantic_score(query: str, document: str, model_name: str = "",
                   _qvec=None) -> float:
    """Cosine score for one passage; callers may reuse an encoded query."""
    model = get_model(model_name)
    if model is None:
        return 0.0
    try:
        query_vector = _qvec
        if query_vector is None:
            query_vector = model.encode([query], normalize_embeddings=True)[0]
        doc_vector = model.encode([document], normalize_embeddings=True)[0]
        return cosine(query_vector, doc_vector)
    except Exception:
        return 0.0


@lru_cache(maxsize=2)
def _cross_encoder(name: str):
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder(name)
    except Exception as exc:
        log.warning("cross-encoder unavailable; keeping hybrid retrieval order",
                    extra={"ctx": {"model": name, "reason": type(exc).__name__}})
        return None


def _probability(score: float) -> float:
    if not math.isfinite(score):
        return 0.0
    if 0.0 <= score <= 1.0:
        return score
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, score))))


def rerank_scores(query: str, texts: list[str], model_name: str) -> list[float] | None:
    """Return cross-encoder relevance scores, or None when unavailable."""
    model = _cross_encoder(model_name) if model_name else None
    if model is None or not texts:
        return None
    try:
        scores = model.predict([(query, text) for text in texts], show_progress_bar=False)
        return [_probability(float(score)) for score in scores]
    except Exception as exc:
        log.warning("cross-encoder scoring failed; keeping hybrid retrieval order",
                    extra={"ctx": {"model": model_name, "reason": type(exc).__name__}})
        return None


def index_corpus_embeddings(conn: sqlite3.Connection, model_name: str,
                            batch_size: int = 32) -> int:
    """Build or replace the persisted dense index for one embedding model."""
    model = get_model(model_name)
    if model is None:
        raise RuntimeError(
            f"Could not load embedding model {model_name!r}; install sentence-transformers "
            "and make the model available before indexing."
        )

    import numpy as np

    rows = conn.execute(
        "SELECT id, chunk_text FROM corpus_chunks ORDER BY id").fetchall()
    conn.execute("DELETE FROM corpus_embeddings WHERE model_name=?", (model_name,))
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        vectors = model.encode(
            [row[1] for row in batch],
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        conn.executemany(
            "INSERT INTO corpus_embeddings(chunk_id, model_name, vector) VALUES (?,?,?)",
            [(row[0], model_name, np.asarray(vector, dtype="<f4").tobytes())
             for row, vector in zip(batch, vectors, strict=True)],
        )
    conn.commit()
    return len(rows)


@lru_cache(maxsize=2)
def _dense_index(db_path: str, model_name: str, db_mtime_ns: int):
    """Cache the persisted float32 matrix until the corpus database changes."""
    import numpy as np

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT chunk_id, vector FROM corpus_embeddings "
            "WHERE model_name=? ORDER BY chunk_id", (model_name,)
        ).fetchall()
    except sqlite3.OperationalError:
        return (), np.empty((0, 0), dtype=np.float32)
    finally:
        conn.close()
    if not rows:
        return (), np.empty((0, 0), dtype=np.float32)
    ids = tuple(int(row[0]) for row in rows)
    matrix = np.stack([np.frombuffer(row[1], dtype="<f4") for row in rows])
    return ids, matrix


def dense_search(db_path: str | Path, query: str, model_name: str,
                 limit: int) -> list[tuple[int, float]]:
    """Search the offline dense index and return (chunk id, cosine score)."""
    if not query.strip():
        return []
    try:
        import numpy as np

        path = str(Path(db_path).resolve())
        ids, matrix = _dense_index(path, model_name, os.stat(path).st_mtime_ns)
        if not ids:
            return []
        model = get_model(model_name)
        if model is None:
            return []
        query_vector = model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        scores = matrix @ query_vector
        count = min(max(1, limit), len(ids))
        positions = np.argsort(scores)[-count:][::-1]
        return [(ids[int(i)], float(scores[i])) for i in positions]
    except Exception as exc:
        log.warning("dense search failed; using lexical search",
                    extra={"ctx": {"model": model_name, "reason": type(exc).__name__}})
        return []
