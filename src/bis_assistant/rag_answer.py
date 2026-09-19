"""Build the /chat answer payload from RAG evidence.

Keeps the deterministic metadata mode untouched (assistant.py falls back to
it when RAG is disabled or finds nothing). When evidence exists:
- try the configurable LLM adapter for a grounded abstractive answer;
- else return a useful extractive answer (never fail for missing creds).
Always attaches `sources` (title/standard number/link) for payload + UI.
"""
from __future__ import annotations

from .allowlist import KYS_PORTAL, safe_public_url
from .i18n_privacy import find_pii
from .rag_llm import extractive_answer, generate_grounded_answer, is_configured
from .safety import BIS_CARE, DISCLAIMER_EN, DISCLAIMER_HI

_PORTAL = KYS_PORTAL

# Bounded in-process TTL cache for grounded LLM text (issue #4 P1-10):
# identical (provider, model, lang, query, evidence) within the TTL reuses
# one generation instead of re-billing the model per repeated turn.
_LLM_CACHE: dict = {}
_LLM_CACHE_MAX = 128


def _norm_query(query: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", (query or "").strip().lower())


def _llm_cache_key(query: str, lang: str, evidence: list[dict],
                   llm_cfg: dict) -> tuple:
    ids = tuple((e.get("standard_number", ""), e.get("chunk_index", 0),
                 e.get("source_file", "")) for e in (evidence or [])[:6])
    return (str(llm_cfg.get("provider", "")), str(llm_cfg.get("model", "")),
            lang, _norm_query(query), ids)


def _llm_cache_get(key: tuple, ttl: int) -> str | None:
    if ttl <= 0:
        return None
    import time as _time
    ent = _LLM_CACHE.get(key)
    if ent is not None and ent[0] > _time.time():
        return ent[1]
    if ent is not None:
        _LLM_CACHE.pop(key, None)
    return None


def _llm_cache_put(key: tuple, text: str, ttl: int) -> None:
    if ttl <= 0 or not text:
        return
    import time as _time
    if len(_LLM_CACHE) >= _LLM_CACHE_MAX:
        _LLM_CACHE.pop(next(iter(_LLM_CACHE)), None)
    _LLM_CACHE[key] = (_time.time() + ttl, text)


def format_rag_citation(e: dict) -> str:
    num = e.get("standard_number") or "BIS document"
    title = e.get("title") or ""
    dtype = e.get("doc_type") or "corpus"
    url = safe_public_url(e.get("source_url"), _PORTAL)
    base = f"{num} — {title} [{dtype}] — Source: {url}" if title else f"{num} [{dtype}] — Source: {url}"
    return base


def build_sources(evidence: list[dict]) -> list[dict]:
    out = []
    for e in evidence:
        out.append({
            "standard_number": e.get("standard_number", ""),
            "title": e.get("title", ""),
            "url": safe_public_url(e.get("source_url"), _PORTAL),
            "doc_type": e.get("doc_type", ""),
            "heading": e.get("heading", ""),
            "chunk_text": (e.get("chunk_text") or "")[:1200],
            "chunk_index": e.get("chunk_index", 0),
            "source_file": e.get("source_file", ""),
            "score": round(float(e.get("score", 0.0)), 3),
        })
    return out


def build_rag_answer(query: str, lang: str, evidence: list[dict],
                     llm_cfg: dict | None = None,
                     extractive_only: bool = False) -> dict:
    hi = lang == "hi"
    if llm_cfg is None:
        from .rag_config import load_llm_config
        llm_cfg = load_llm_config()
    citations = [format_rag_citation(e) for e in evidence[:5]]
    sources = build_sources(evidence)
    used_llm = False
    text = None
    try:
        cache_ttl = int((llm_cfg or {}).get("cache_ttl", 300))
    except (TypeError, ValueError):
        cache_ttl = 300
    cache_key = None
    if evidence and not extractive_only and is_configured(llm_cfg):
        cache_key = _llm_cache_key(query, lang, evidence, llm_cfg)
        text = _llm_cache_get(cache_key, cache_ttl)
        used_llm = text is not None
        if text is None:
            text = generate_grounded_answer(query, evidence, lang, llm_cfg)
            used_llm = text is not None
            if used_llm:
                _llm_cache_put(cache_key, text, cache_ttl)
    if not text:
        text = extractive_answer(query, evidence, lang)
    lines = [text.rstrip(), "", "---",
             DISCLAIMER_HI if hi else DISCLAIMER_EN, BIS_CARE]
    if used_llm:
        mode = f"grounded LLM ({llm_cfg.get('model')})"
    else:
        mode = "extractive (no LLM configured)"
    return {
        "text": "\n".join(lines),
        "refused": False,
        "kind": "corpus_answer",
        "lang": lang,
        "citations": citations,
        "sources": sources,
        "rag_evidence": sources,
        "rag_mode": mode,
        "rag_used_llm": used_llm,
        "pii": find_pii(query),
        "needs_info": False,
        "questions": [],
        "known": [],
        "assumptions": [],
        "context": {"history": [], "rounds": 0},
    }
