"""RAG configuration: env + config.yaml `rag`/`llm` sections. Backward compatible.

Switches:
  BIS_RAG_ENABLED=1|true|yes      enable corpus retrieval in /chat
  BIS_RAG_DB_PATH=kb/bis_rag.db   SQLite corpus index
  BIS_RAG_TOP_K=5                 evidence chunks per query
  BIS_RAG_SEMANTIC=1              enable semantic rerank channel (default on)
  BIS_RAG_EMBEDDING_MODEL=""      optional sentence-transformers model name
  BIS_LLM_MODEL=""                e.g. gpt-4o-mini / gemini-2.0-flash / llama3
  BIS_LLM_PROVIDER="openai-compatible"  openai-compatible | gemini | ollama
  BIS_LLM_API_KEY=""              never hard-code; env/config only
  BIS_LLM_BASE_URL="https://api.openai.com/v1"  (ollama default http://localhost:11434)
  BIS_LLM_TEMPERATURE=0.2
  BIS_LLM_MAX_TOKENS=768
  BIS_LLM_TIMEOUT_S=10
  BIS_LLM_RETRIES=0
  BIS_LLM_CACHE_TTL=300       seconds to reuse a grounded answer for an
                              identical (query, evidence, lang); 0 disables
  BIS_RAG_CATALOGUE=1             24k catalogue fallback for novel products
  BIS_GUIDANCE_ADAPTIVE=1         user-tailored certification next steps
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = str(REPO_ROOT / "kb" / "bis_rag.db")


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _cfg_section(name: str) -> dict:
    try:
        from .config import load as load_config
        cfg = load_config()
        sec = cfg.get(name, {})
        return dict(sec) if isinstance(sec, dict) else {}
    except Exception:
        return {}


def load_rag_config() -> dict:
    file_cfg = _cfg_section("rag")
    return {
        "enabled": _bool_env("BIS_RAG_ENABLED", bool(file_cfg.get("enabled", False))),
        "db_path": os.environ.get("BIS_RAG_DB_PATH", str(file_cfg.get("db_path", DEFAULT_DB))),
        "top_k": _int_env("BIS_RAG_TOP_K", int(file_cfg.get("top_k", 5))),
        "semantic": _bool_env("BIS_RAG_SEMANTIC", bool(file_cfg.get("semantic", True))),
        "embedding_model": os.environ.get(
            "BIS_RAG_EMBEDDING_MODEL", str(file_cfg.get("embedding_model", ""))),
        "weight_lexical": _float_env(
            "BIS_RAG_WEIGHT_LEXICAL", float(file_cfg.get("weight_lexical", 1.0))),
        "weight_semantic": _float_env(
            "BIS_RAG_WEIGHT_SEMANTIC", float(file_cfg.get("weight_semantic", 0.3))),
        "exact_boost": _float_env(
            "BIS_RAG_EXACT_BOOST", float(file_cfg.get("exact_boost", 50.0))),
        "min_overlap": _int_env(
            "BIS_RAG_MIN_OVERLAP", int(file_cfg.get("min_overlap", 3))),
        "min_lexical": _float_env(
            "BIS_RAG_MIN_LEXICAL", float(file_cfg.get("min_lexical", 15.0))),
        "catalogue_min_score": _float_env(
            "BIS_RAG_CATALOGUE_MIN_SCORE",
            float(file_cfg.get("catalogue_min_score", 8.0))),
    }


def load_llm_config() -> dict:
    file_cfg = _cfg_section("llm")
    provider = os.environ.get(
        "BIS_LLM_PROVIDER", str(file_cfg.get("provider", "openai-compatible")))
    # Provider-aware endpoint defaults: an explicit BIS_LLM_BASE_URL (or a
    # non-default file value) always wins; otherwise gemini/ollama get their
    # own defaults instead of inheriting the OpenAI one from config.yaml.
    _OPENAI_DEFAULT = "https://api.openai.com/v1"
    _PROVIDER_DEFAULTS = {
        "gemini": "https://generativelanguage.googleapis.com",
        "ollama": "http://localhost:11434",
    }
    if "BIS_LLM_BASE_URL" in os.environ:
        base = os.environ["BIS_LLM_BASE_URL"]
    elif str(file_cfg.get("base_url", "")) not in ("", _OPENAI_DEFAULT) \
            or provider not in _PROVIDER_DEFAULTS:
        base = str(file_cfg.get("base_url", _OPENAI_DEFAULT))
    else:
        base = _PROVIDER_DEFAULTS[provider]
    return {
        "provider": provider,
        "model": os.environ.get("BIS_LLM_MODEL", str(file_cfg.get("model", ""))),
        "api_key": os.environ.get("BIS_LLM_API_KEY", str(file_cfg.get("api_key", ""))),
        "base_url": base.rstrip("/"),
        "temperature": _float_env(
            "BIS_LLM_TEMPERATURE", float(file_cfg.get("temperature", 0.2))),
        "max_tokens": _int_env(
            "BIS_LLM_MAX_TOKENS", int(file_cfg.get("max_tokens", 768))),
        "timeout_s": _float_env(
            "BIS_LLM_TIMEOUT_S", float(file_cfg.get("timeout_s", 10.0))),
        "retries": _int_env(
            "BIS_LLM_RETRIES", int(file_cfg.get("retries", 0))),
        "cache_ttl": _int_env(
            "BIS_LLM_CACHE_TTL", int(file_cfg.get("cache_ttl", 300))),
    }


def load_guidance_config() -> dict:
    file_cfg = _cfg_section("guidance")
    # Catalogue has its own flag, decoupled from the corpus (issue #4 P0-1).
    # Legacy BIS_RAG_CATALOGUE / rag.catalogue still honored as fallback.
    cat_file = _cfg_section("catalogue")
    if "enabled" not in cat_file:
        legacy = _cfg_section("rag").get("catalogue", True)
        cat_file = {"enabled": legacy}
    if "BIS_CATALOGUE_ENABLED" in os.environ:
        catalogue_on = _bool_env("BIS_CATALOGUE_ENABLED", True)
    else:  # legacy knob honored until removed
        catalogue_on = _bool_env("BIS_RAG_CATALOGUE",
                                 bool(cat_file.get("enabled", True)))
    return {
        "adaptive": _bool_env("BIS_GUIDANCE_ADAPTIVE",
                              bool(file_cfg.get("adaptive", True))),
        "catalogue": catalogue_on,
    }


def is_enabled() -> bool:
    return load_rag_config()["enabled"]
