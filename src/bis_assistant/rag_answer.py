"""Build the /chat answer payload from RAG evidence.

Keeps the deterministic metadata mode untouched (assistant.py falls back to
it when RAG is disabled or finds nothing). When evidence exists:
- try the configurable LLM adapter for a grounded abstractive answer;
- else return a useful extractive answer (never fail for missing creds).
Always attaches `sources` (title/standard number/link) for payload + UI.
"""
from __future__ import annotations

from .i18n_privacy import find_pii
from .rag_llm import extractive_answer, generate_grounded_answer, is_configured
from .safety import BIS_CARE, DISCLAIMER_EN, DISCLAIMER_HI

_PORTAL = "https://www.bis.gov.in/know-your-standard"


def format_rag_citation(e: dict) -> str:
    num = e.get("standard_number") or "BIS document"
    title = e.get("title") or ""
    dtype = e.get("doc_type") or "corpus"
    url = e.get("source_url") or _PORTAL
    base = f"{num} — {title} [{dtype}] — Source: {url}" if title else f"{num} [{dtype}] — Source: {url}"
    return base


def build_sources(evidence: list[dict]) -> list[dict]:
    out = []
    for e in evidence:
        out.append({
            "standard_number": e.get("standard_number", ""),
            "title": e.get("title", ""),
            "url": e.get("source_url", ""),
            "doc_type": e.get("doc_type", ""),
            "heading": e.get("heading", ""),
            "chunk_text": (e.get("chunk_text") or "")[:1200],
            "chunk_index": e.get("chunk_index", 0),
            "source_file": e.get("source_file", ""),
            "score": round(float(e.get("score", 0.0)), 3),
        })
    return out


def build_rag_answer(query: str, lang: str, evidence: list[dict],
                     llm_cfg: dict | None = None) -> dict:
    hi = lang == "hi"
    if llm_cfg is None:
        from .rag_config import load_llm_config
        llm_cfg = load_llm_config()
    citations = [format_rag_citation(e) for e in evidence[:5]]
    sources = build_sources(evidence)
    used_llm = False
    text = None
    if evidence and is_configured(llm_cfg):
        text = generate_grounded_answer(query, evidence, lang, llm_cfg)
        used_llm = text is not None
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
