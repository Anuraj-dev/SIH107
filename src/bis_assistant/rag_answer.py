"""Create chat responses only from model-generated text."""
from __future__ import annotations

import logging

from .allowlist import KYS_PORTAL, safe_public_url
from .i18n_privacy import find_pii
from .rag_llm import MAX_EVIDENCE_SOURCES, generate_grounded_answer, is_configured

log = logging.getLogger("bis.api")


def format_rag_citation(e: dict) -> str:
    num = e.get("standard_number") or "BIS document"
    title = e.get("title") or ""
    dtype = e.get("doc_type") or "lab"
    url = safe_public_url(e.get("source_url"), KYS_PORTAL)
    base = f"{num} — {title} [{dtype}] — Source: {url}" if title else f"{num} [{dtype}] — Source: {url}"
    return base


def build_sources(evidence: list[dict]) -> list[dict]:
    return [{
        "standard_number": e.get("standard_number", ""),
        "title": e.get("title", ""),
        "url": safe_public_url(e.get("source_url"), KYS_PORTAL),
        "doc_type": e.get("doc_type", ""),
        "heading": e.get("heading", ""),
        "chunk_text": (e.get("chunk_text") or "")[:1200],
        "chunk_index": e.get("chunk_index", 0),
        "source_file": e.get("source_file", ""),
        "score": round(float(e.get("score", 0.0)), 3),
    } for e in evidence]


def model_unavailable_response(query: str, lang: str = "en") -> dict:
    """Return a service-state notice, never a substitute answer."""
    text = (
        "चैटबॉट अभी उपलब्ध नहीं है क्योंकि भाषा मॉडल उपलब्ध नहीं है। कृपया बाद में फिर कोशिश करें।"
        if lang == "hi" else
        "The chatbot is offline because its language model is unavailable. Please try again later."
    )
    return {
        "text": text,
        "refused": False,
        "kind": "model_unavailable",
        "lang": lang,
        "citations": [],
        "sources": [],
        "rag_evidence": [],
        "rag_mode": "model unavailable",
        "rag_used_llm": False,
        "model_available": False,
        "pii": find_pii(query),
        "needs_info": False,
        "questions": [],
        "known": [],
        "assumptions": [],
        "context": {"history": [], "rounds": 0},
    }


def build_rag_answer(query: str, lang: str, evidence: list[dict],
                     llm_cfg: dict | None = None,
                     history: list[str] | None = None) -> dict:
    """Retrieve evidence for the model and return its answer or offline state.

    Empty evidence is still sent to the model so it can answer trusted runtime
    facts or explain that the BIS corpus has no support. Retrieved chunks are never
    used as answer text.
    """
    try:
        if not is_configured(llm_cfg):
            return model_unavailable_response(query, lang)
        text = generate_grounded_answer(
            query, evidence, lang, llm_cfg, history=history)
    except Exception:
        log.exception("LLM answer generation failed")
        return model_unavailable_response(query, lang)

    if not text or not text.strip():
        return model_unavailable_response(query, lang)

    return {
        "text": text.strip(),
        "refused": False,
        "kind": "llm_answer",
        "lang": lang,
        "citations": [format_rag_citation(e) for e in evidence[:MAX_EVIDENCE_SOURCES]],
        "sources": build_sources(evidence[:MAX_EVIDENCE_SOURCES]),
        "rag_evidence": build_sources(evidence[:MAX_EVIDENCE_SOURCES]),
        "rag_mode": "llm",
        "rag_used_llm": True,
        "model_available": True,
        "pii": find_pii(query),
        "needs_info": False,
        "questions": [],
        "known": [],
        "assumptions": [],
        "context": {"history": [], "rounds": 0},
    }
