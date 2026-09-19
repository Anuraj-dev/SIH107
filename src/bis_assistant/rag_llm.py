"""LLM generation adapter (provider-aware) + extractive fallback.

Providers (``BIS_LLM_PROVIDER``, also ``llm.provider`` in config.yaml):
- ``openai-compatible`` (default): POST ``{base}/chat/completions`` with a
  Bearer key. Covers OpenAI, Together, OpenRouter, local vLLM servers, and
  Ollama's OpenAI endpoint. Needs ``BIS_LLM_MODEL`` + ``BIS_LLM_API_KEY``.
- ``gemini``: POST ``{base}/v1beta/models/{model}:generateContent?key=...``
  with ``BIS_LLM_MODEL`` (e.g. ``gemini-2.0-flash``) + ``BIS_LLM_API_KEY``.
- ``ollama``: POST ``{base}/api/chat`` (default ``http://localhost:11434``,
  an open-source local path). Needs only ``BIS_LLM_MODEL`` (e.g. ``llama3``);
  no key is required.

Secrets come from env/config only — never hard-coded. Stdlib-only HTTP
(urllib) so the project stays dependency-free. ``BIS_LLM_RETRIES`` controls
extra attempts on transport failures AND empty responses (default 0 keeps
interactive /chat inside the latency budget). When no LLM is configured
— or every attempt fails — callers use extractive_answer(), which never fails.
"""
from __future__ import annotations

import json
import urllib.request

from .allowlist import safe_public_url
from .rag_config import load_llm_config


def is_configured(cfg: dict | None = None) -> bool:
    cfg = cfg or load_llm_config()
    provider = str(cfg.get("provider", "openai-compatible")).lower()
    if provider == "ollama":
        return bool(cfg.get("model"))
    return bool(cfg.get("api_key") and cfg.get("model"))


def _prompt(query: str, evidence: list[dict], lang: str) -> tuple[str, str]:
    lang_line = "Respond in Hindi (Devanagari-friendly, simple words)." \
        if lang == "hi" else "Respond in English."
    ctx_parts = []
    for i, e in enumerate(evidence[:6], 1):
        ctx_parts.append(
            f"[{i}] {e.get('standard_number','')} — {e.get('title','')}"
            f" ({e.get('doc_type','')}){(' — ' + e['heading']) if e.get('heading') else ''}\n"
            f"{e.get('chunk_text','')[:1500]}")
    context = "\n\n".join(ctx_parts)
    system = ("You answer questions about BIS Indian Standards using ONLY the provided"
              " evidence passages. Be concise and grounded: cite the standard number for"
              " every claim like [IS 101 (Part 2/Sec 6):2026]. If the evidence does not"
              " contain the answer, say so and point to BIS Know-Your-Standard."
              " Never invent clause wording, test results, approvals or timelines. "
              + lang_line)
    user = f"Question: {query}\n\nEvidence:\n{context}\n\nAnswer with citations to the evidence."
    return system, user


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _send_openai_compatible(messages: list[dict], cfg: dict) -> str | None:
    url = cfg.get("base_url", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.2),
        "max_tokens": cfg.get("max_tokens", 768),
    }
    body = _post_json(url, payload, {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}"}, cfg.get("timeout_s", 10.0))
    choices = body.get("choices", [])
    if choices:
        text = (choices[0].get("message", {}).get("content") or "").strip()
        return text or None
    return None


def _send_ollama(messages: list[dict], cfg: dict) -> str | None:
    url = cfg.get("base_url", "http://localhost:11434").rstrip("/") + "/api/chat"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": False,
        "options": {"temperature": cfg.get("temperature", 0.2),
                    "num_predict": cfg.get("max_tokens", 768)},
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = _post_json(url, payload, headers, cfg.get("timeout_s", 10.0))
    text = ((body.get("message", {}) or {}).get("content") or "").strip()
    return text or None


def _send_gemini(messages: list[dict], cfg: dict) -> str | None:
    base = cfg.get("base_url", "https://generativelanguage.googleapis.com").rstrip("/")
    url = f"{base}/v1beta/models/{cfg['model']}:generateContent?key={cfg['api_key']}"
    # System prompt travels as systemInstruction (issue #4 P1-11): folding
    # it into the user turn weakened grounding on long evidence prompts.
    system = "\n\n".join(m.get("content", "") for m in messages
                         if m.get("role") == "system")
    user = "\n\n".join(m.get("content", "") for m in messages
                       if m.get("role") != "system") or "\n\n".join(
        m.get("content", "") for m in messages)
    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": cfg.get("temperature", 0.2),
                             "maxOutputTokens": cfg.get("max_tokens", 768)},
    }
    if system:
        payload["system_instruction"] = {"parts": [{"text": system}]}
    body = _post_json(url, payload, {"Content-Type": "application/json"},
                      cfg.get("timeout_s", 10.0))
    # Scan all candidates: reasoning models may return an empty first
    # candidate (e.g. thinking consumed the token budget) while a later
    # one carries text.
    for cand in body.get("candidates", []):
        parts = ((cand.get("content", {}) or {}).get("parts", []) or [])
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        if text:
            return text
    return None


_SENDERS = {
    "openai": _send_openai_compatible,
    "openai-compatible": _send_openai_compatible,
    "ollama": _send_ollama,
    "gemini": _send_gemini,
}


def chat_complete(messages: list[dict], cfg: dict | None = None) -> str | None:
    """Provider-dispatched chat call with retries. None on any failure.

    Both transport errors AND empty-string successes consume an attempt
    (issue #4 P1-11): an empty candidate usually means the thinking/model
    budget ran out, which a retry with the same prompt can recover from.
    """
    cfg = cfg or load_llm_config()
    if not is_configured(cfg):
        return None
    provider = str(cfg.get("provider", "openai-compatible")).lower()
    sender = _SENDERS.get(provider, _send_openai_compatible)
    attempts = 1 + max(0, int(cfg.get("retries", 0)))
    for _ in range(attempts):
        try:
            text = sender(messages, cfg)
            if text:
                return text
        except Exception:
            continue
    return None


def generate_grounded_answer(query: str, evidence: list[dict],
                             lang: str = "en",
                             cfg: dict | None = None) -> str | None:
    """Grounded abstractive answer. None when unconfigured or on failure."""
    cfg = cfg or load_llm_config()
    if not is_configured(cfg) or not evidence:
        return None
    system, user = _prompt(query, evidence, lang)
    return chat_complete([{"role": "system", "content": system},
                          {"role": "user", "content": user}], cfg)


def extractive_answer(query: str, evidence: list[dict], lang: str = "en") -> str:
    """Deterministic fallback: best matching passages, no LLM needed."""
    hi = lang == "hi"
    if not evidence:
        return ("Iske liye corpus me prasangik ansh nahin mila." if hi
                else "No relevant passages found in the corpus index.")
    head = ("Neeche corpus ke sabse prasangik ansh hain (extractive, bina LLM):" if hi
            else "Most relevant corpus passages (extractive answer, no LLM configured):")
    lines = [head, ""]
    for e in evidence[:4]:
        title = e.get("title") or e.get("standard_number") or "BIS document"
        lines.append(f"- **{e.get('standard_number','')}** — {title}")
        if e.get("heading"):
            lines.append(f"  Section: {e['heading']}")
        raw = " ".join((e.get("chunk_text") or "").split())
        snippet = raw[:600]
        if len(raw) > 600:
            snippet = snippet.rsplit(" ", 1)[0]
        lines.append(f"  > {snippet}")
        if e.get("source_url"):
            lines.append(f"  Source: {safe_public_url(e.get('source_url'))}")
        lines.append("")
    lines.append("Match the IS number/year against the BIS catalogue before relying on this; "
                 "verify status on Know-Your-Standard." if not hi else
                 "Bharosa karne se pehle IS number/varsh BIS catalogue se milayen.")
    return "\n".join(lines).strip()
