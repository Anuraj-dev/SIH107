"""Translation helper: LLM-powered when configured, else explicit fallback.

EN↔HI keyword dictionaries (see ``retriever.HINGLISH``/``DEVANAGARI``) cover
the common BIS vocabulary offline. For anything beyond that,
``translate_text`` uses the configured LLM provider (OpenAI-compatible,
Gemini or local Ollama) as a translation API and returns None when no LLM
is available, so callers always fall back to the dictionaries.
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
