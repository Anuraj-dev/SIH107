"""Optional vector/semantic embeddings for RAG fusion.

Default channel (no installs): hashed token vectors give a *lexical
similarity* cosine — cheap and dependency-free, but honest about what it
is: it reranks by token overlap, not meaning. For true semantic vectors,
set ``BIS_RAG_EMBEDDING_MODEL`` to a sentence-transformers model; the
retriever then batch-encodes (one query + one batch call per search).
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

_DIM = 256
_tok_re = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(s: str) -> list[str]:
    return _tok_re.findall(s.lower())


def hash_embed(text: str, dim: int = _DIM) -> list[float]:
    vec = [0.0] * dim
    for t in _tokens(text):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _st_model(name: str):
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer(name)
    except Exception:
        return None


@lru_cache(maxsize=2)
def _cached_st(name: str):
    return _st_model(name)


def get_model(name: str):
    """Resolve a sentence-transformers model or None (cached, never raises)."""
    if not name:
        return None
    try:
        return _cached_st(name)
    except Exception:
        return None


def embed_query(query: str, model_name: str = ""):
    if model_name:
        m = _cached_st(model_name)
        if m is not None:
            try:
                v = m.encode([query], normalize_embeddings=True)[0]
                return ("st", [float(x) for x in v])
            except Exception:
                pass
    return ("hash", hash_embed(query))


def embed_texts(texts: list[str], model_name: str = ""):
    if model_name:
        m = _cached_st(model_name)
        if m is not None:
            try:
                mat = m.encode(texts, normalize_embeddings=True)
                return [("st", [float(x) for x in row]) for row in mat]
            except Exception:
                pass
    return [("hash", hash_embed(t)) for t in texts]


def semantic_score(query: str, doc: str, model_name: str = "",
                   _qvec=None) -> float:
    """Cosine similarity in [0,1]. A passed ``_qvec`` is reused so callers
    never re-encode the query per chunk (issue #4 P1-9)."""
    if model_name:
        m = get_model(model_name)
        if m is not None:
            try:
                qv = _qvec
                if qv is None or (isinstance(qv, tuple)):
                    qv = [float(x) for x in
                          m.encode([query], normalize_embeddings=True)[0]]
                else:
                    qv = [float(x) for x in qv]
                dv = [float(x) for x in
                      m.encode([doc], normalize_embeddings=True)[0]]
                return float(sum(a * b for a, b in zip(qv, dv)))
            except Exception:
                pass
    qv = _qvec if _qvec is not None and not isinstance(_qvec, tuple) \
        else None
    if qv is None:
        try:
            qv = hash_embed(query)
        except Exception:
            return 0.0
    try:
        return cosine([float(x) for x in qv], hash_embed(doc))
    except Exception:
        return 0.0
