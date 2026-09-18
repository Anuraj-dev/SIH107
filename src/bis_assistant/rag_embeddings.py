"""Optional vector/semantic embeddings for RAG fusion.

Clean, dependency-free default: hashed token vectors (stdlib) give a cosine
"semantic" channel with no installs. If BIS_RAG_EMBEDDING_MODEL names a
sentence-transformers model and that package is installed, it is used
instead (configurable embeddings per task spec).
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
    """Cosine similarity in [0,1]. Falls back to hashed vectors (no deps)."""
    if model_name:
        m = _cached_st(model_name)
        if m is not None:
            try:
                import numpy as _np  # noqa: F401 - probe only
                qv = m.encode([query], normalize_embeddings=True)[0]
                dv = m.encode([doc], normalize_embeddings=True)[0]
                return float(sum(float(a) * float(b) for a, b in zip(qv, dv)))
            except Exception:
                pass
    qv = _qvec if _qvec is not None else hash_embed(query)
    dv = hash_embed(doc)
    return cosine(qv, dv)
