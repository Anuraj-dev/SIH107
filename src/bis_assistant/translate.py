"""Standalone translation helper; chat answer generation does not use it.

``translate_text`` uses the configured LLM provider (OpenAI-compatible,
Gemini or local Ollama) and returns None when no LLM is available. It is not
called by the chat endpoint and never supplies a substitute chat answer.
"""
from __future__ import annotations


def translate_text(text: str, target: str = "hi",
                   cfg: dict | None = None) -> str | None:
    """Translate ``text`` to ``target`` ("hi"|"en"). None when unavailable."""
    t = (text or "").strip()
    if not t or target not in ("hi", "en"):
        return None
    try:
        from .rag_config import load_llm_config
        from .rag_llm import chat_complete, is_configured
        cfg = cfg or load_llm_config()
        if not is_configured(cfg):
            return None
        lang = "Hindi (simple words)" if target == "hi" else "English"
        out = chat_complete([
            {"role": "system",
             "content": "You are a precise translator. Translate exactly, "
                        "keep product names, numbers and IS designations unchanged."},
            {"role": "user",
             "content": f"Translate to {lang}:\n{t}"}], cfg)
        return out.strip() if out and out.strip() else None
    except Exception:
        return None
