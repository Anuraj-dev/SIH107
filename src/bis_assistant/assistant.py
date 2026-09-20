"""Single LLM-backed chat path with retrieved BIS evidence as model context."""
from __future__ import annotations

import logging

from .i18n_privacy import detect_lang, redact
from .rag_answer import build_rag_answer
from .rag_llm import (
    is_configured,
    is_runtime_identity_query,
    is_underspecified_standard_query,
)
from .rag_config import load_llm_config, load_rag_config
from . import threads as threadmod

log = logging.getLogger("bis.api")


def _rag_lookup(text: str, top_k: int | None = None,
                _conn=None) -> tuple[list[dict], dict]:
    """Fetch BIS corpus passages for the model. Errors produce no context."""
    try:
        from .rag_retriever import search_rag

        cfg = load_rag_config()
        if not cfg.get("enabled"):
            return [], cfg
        evidence = search_rag(
            text,
            top_k=top_k or cfg.get("top_k", 5),
            db_path=cfg.get("db_path"),
            lexical_weight=cfg.get("weight_lexical", 1.0),
            semantic_weight=cfg.get("weight_semantic", 0.3),
            exact_boost=cfg.get("exact_boost", 50.0),
            semantic=cfg.get("semantic", True),
            embedding_model=cfg.get("embedding_model", ""),
            _conn=_conn,
        )
        return evidence or [], cfg
    except Exception:
        log.exception("BIS corpus retrieval failed; the model will receive no evidence")
        return [], {}


def answer(query: str, lang: str | None = None,
           context: dict | None = None) -> dict:
    """Return an LLM answer or an explicit model-unavailable state.

    Every valid chat turn uses one model generation. BIS evidence only enters
    the prompt as context; this module never renders retrieved text as an
    answer or substitutes deterministic catalogue/slot responses.
    """
    q = (query or "").strip()
    resolved_lang = lang if lang in ("en", "hi") else detect_lang(q)
    turn_context = threadmod.normalize_context(context)

    try:
        llm_cfg = load_llm_config()
        configured = is_configured(llm_cfg)
    except Exception:
        log.exception("Could not load LLM configuration")
        llm_cfg = {}
        configured = False

    evidence: list[dict] = []
    if configured and not is_runtime_identity_query(q) \
            and not is_underspecified_standard_query(q):
        evidence, _ = _rag_lookup(q)

    response = build_rag_answer(
        q,
        resolved_lang,
        evidence,
        llm_cfg,
        history=turn_context["history"],
    )
    response["context"] = {
        "history": threadmod.push_history(
            turn_context["history"], redact(q)[:2000]) if q else turn_context["history"],
        "rounds": turn_context["rounds"],
        "force": turn_context["force"],
    }
    response["intent"] = "general"
    response["intent_confidence"] = "low"
    response["context_summary"] = ""
    return response
