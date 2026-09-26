"""Create chat responses only from model-generated text."""
from __future__ import annotations

import logging

from .allowlist import KYS_PORTAL, safe_public_url
from .i18n_privacy import find_pii
from .rag_llm import (
    MAX_EVIDENCE_SOURCES,
    generate_grounded_answer,
    is_configured,
    is_runtime_identity_query,
    is_underspecified_standard_query,
)
from .verifier import evidence_type, verify_grounded_response

log = logging.getLogger("bis.api")


def format_rag_citation(e: dict) -> str:
    num = e.get("standard_number") or "BIS document"
    title = e.get("title") or ""
    url = safe_public_url(e.get("source_url"), KYS_PORTAL)
    if evidence_type(e) == "catalogue_record":
        return f"{num}: {title} [catalogue metadata only], Source: {url}"
    dtype = e.get("doc_type") or "lab"
    base = f"{num}: {title} [{dtype}], Source: {url}" if title else f"{num} [{dtype}], Source: {url}"
    return base


def build_sources(evidence: list[dict]) -> list[dict]:
    sources = []
    for e in evidence:
        source = {
            "evidence_type": evidence_type(e),
            "standard_number": e.get("standard_number", ""),
            "title": e.get("title", ""),
            "url": safe_public_url(e.get("source_url"), KYS_PORTAL),
            "doc_type": e.get("doc_type", e.get("type", "")),
            "score": round(float(e.get("score", 0.0) or 0.0), 3),
        }
        if source["evidence_type"] == "catalogue_record":
            source["metadata_only"] = True
            source["department"] = e.get("department", e.get("committee", ""))
            source["date"] = e.get("published_on", e.get("date", ""))
        else:
            source.update({
                "heading": e.get("heading", ""),
                "chunk_text": (e.get("chunk_text") or "")[:1200],
                "chunk_index": e.get("chunk_index", 0),
                "source_file": e.get("source_file", ""),
            })
        for key in ("rank", "selection_reason"):
            if key in e:
                source[key] = e[key]
        sources.append(source)
    return sources


def grounding_failure_response(query: str, lang: str = "en") -> dict:
    """Fail closed when one model repair still contains unsupported claims."""
    text = (
        "मैं उपलब्ध साक्ष्य से सुरक्षित उत्तर की पुष्टि नहीं कर सकता। कृपया मानक का पूरा पाठ या अपने उत्पाद की सामग्री और उपयोग साझा करें।"
        if lang == "hi" else
        "I can’t safely verify an answer from the retrieved evidence. Please share the full standard text or your product’s material and intended use."
    )
    return {
        "text": text,
        "refused": True,
        "kind": "grounding_refusal",
        "lang": lang,
        "citations": [],
        "sources": [],
        "rag_evidence": [],
        "rag_mode": "llm_grounding_guard",
        "rag_used_llm": True,
        "model_available": True,
        "pii": find_pii(query),
        "needs_info": True,
        "questions": [],
        "known": [],
        "assumptions": [],
        "context": {"history": [], "rounds": 0},
    }


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
        if is_runtime_identity_query(query) or is_underspecified_standard_query(query):
            evidence = []
        answer_evidence = evidence[:MAX_EVIDENCE_SOURCES]
        text = generate_grounded_answer(
            query, answer_evidence, lang, llm_cfg, history=history)
    except Exception:
        log.exception("LLM answer generation failed")
        return model_unavailable_response(query, lang)

    if not text or not text.strip():
        return model_unavailable_response(query, lang)

    violations = verify_grounded_response(text, answer_evidence)
    if violations:
        log.warning("LLM answer failed grounding validation",
                    extra={"ctx": {"issue_codes": violations}})
        try:
            repaired = generate_grounded_answer(
                query, answer_evidence, lang, llm_cfg, history=history,
                retry_feedback=violations)
        except Exception:
            log.exception("LLM grounding repair failed")
            repaired = None
        if repaired and not verify_grounded_response(repaired, answer_evidence):
            text = repaired
        else:
            return grounding_failure_response(query, lang)

    shown = answer_evidence
    low = text.lower()
    if ("does not contain enough information" in low
            or is_underspecified_standard_query(query)
            or is_runtime_identity_query(query)):
        shown = []

    return {
        "text": text.strip(),
        "refused": False,
        "kind": "llm_answer",
        "lang": lang,
        "citations": [format_rag_citation(e) for e in shown],
        "sources": build_sources(shown),
        "rag_evidence": build_sources(shown),
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
