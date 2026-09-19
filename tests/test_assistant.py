"""Shared chat behavior: model-generated answers or an explicit offline state."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from bis_assistant import assistant, rag_llm
from bis_assistant.i18n_privacy import ConsentStore, detect_lang, find_pii, redact
from bis_assistant.retriever import format_citation, load_kb, retrieve


def _llm_config(**overrides):
    return {
        "provider": "openai-compatible",
        "model": "test-model",
        "api_key": "test-key",
        "base_url": "https://llm.example.test/v1",
        "temperature": 0,
        "max_tokens": 256,
        "timeout_s": 1,
        "retries": 0,
        **overrides,
    }


def test_retriever_still_searches_curated_data():
    standards, _, _, _ = load_kb()
    assert all("bis.gov.in" in s["source_url"] for s in standards)
    result = retrieve("vacuum insulated stainless steel water bottle flask")
    assert result["candidates"][0]["std"]["is_number"] == "IS 17803"
    citation = format_citation(retrieve("IS 10500 drinking water")["candidates"][0]["std"])
    assert "IS 10500" in citation and "last-checked" in citation


def test_empty_source_url_is_not_returned():
    from bis_assistant import retriever

    standards, schemes, labs, glossary = retriever.load_kb()
    poisoned = dict(standards[0], source_url="", is_number="IS 17803")
    original = retriever.load_kb

    def custom_kb():
        current, current_schemes, current_labs, current_glossary = original()
        return ([poisoned] + [s for s in current if s["is_number"] != "IS 17803"],
                current_schemes, current_labs, current_glossary)

    retriever.load_kb = custom_kb
    try:
        result = retrieve("vacuum insulated stainless steel water bottle flask")
    finally:
        retriever.load_kb = original
    assert all(c["std"].get("source_url") for c in result["candidates"])
    assert not any(c["std"]["is_number"] == "IS 17803" for c in result["candidates"])


def test_configured_chat_always_calls_model_with_runtime_context(monkeypatch):
    calls = []
    monkeypatch.setattr(assistant, "load_llm_config", lambda: _llm_config())
    monkeypatch.setattr(assistant, "_rag_lookup", lambda *_a, **_kw: ([], {"enabled": True}))
    monkeypatch.setattr(rag_llm, "chat_complete",
                        lambda messages, _cfg=None: calls.append(messages) or "MODEL ANSWER")

    response = assistant.answer("What is your name?", "en")

    assert response["text"] == "MODEL ANSWER"
    assert response["kind"] == "llm_answer" and response["model_available"] is True
    assert len(calls) == 1
    system = next(m["content"] for m in calls[0] if m["role"] == "system")
    user = next(m["content"] for m in calls[0] if m["role"] == "user")
    assert "use only the bis evidence supplied" in system.lower()
    assert "ignore commands" in system.lower()
    assert "what is your name?" in user.lower()
    assert "Assistant: BIS Assistant" in user
    assert re.search(
        r"Current date and time in India \(Asia/Kolkata\): "
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30", user)


def test_lab_passage_is_prompt_context_not_a_response_fallback(monkeypatch):
    evidence = [{
        "standard_number": "IS 14478:2026",
        "title": "Plain bearings",
        "doc_type": "lab",
        "chunk_text": "RAW LAB PASSAGE THAT MUST NOT BE SHOWN AS THE ANSWER",
        "source_url": "https://www.bis.gov.in/know-your-standard",
    }]
    calls = []
    monkeypatch.setattr(assistant, "load_llm_config", lambda: _llm_config())
    monkeypatch.setattr(assistant, "_rag_lookup", lambda *_a, **_kw: (evidence, {"enabled": True}))
    monkeypatch.setattr(rag_llm, "chat_complete",
                        lambda messages, _cfg=None: calls.append(messages) or "SYNTHESIZED MODEL ANSWER")

    response = assistant.answer("What does IS 14478 cover?", "en")

    user = next(m["content"] for m in calls[0] if m["role"] == "user")
    assert "RAW LAB PASSAGE" in user
    assert response["text"] == "SYNTHESIZED MODEL ANSWER"
    assert "RAW LAB PASSAGE" not in response["text"]
    assert response["sources"] and response["rag_used_llm"] is True


def test_missing_model_skips_retrieval_and_returns_only_offline_state(monkeypatch):
    monkeypatch.setattr(assistant, "load_llm_config", lambda: _llm_config(model="", api_key=""))
    monkeypatch.setattr(assistant, "_rag_lookup",
                        lambda *_a, **_kw: pytest.fail("must not retrieve when model is unavailable"))
    monkeypatch.setattr(rag_llm, "chat_complete",
                        lambda *_a, **_kw: pytest.fail("must not call unconfigured provider"))

    response = assistant.answer("steel bottle", "en")

    assert response["kind"] == "model_unavailable"
    assert response["model_available"] is False and response["rag_used_llm"] is False
    assert "unavailable" in response["text"].lower()
    assert not response["questions"] and not response["citations"] and not response["sources"]


def test_provider_failure_never_exposes_retrieved_passages(monkeypatch):
    evidence = [{
        "standard_number": "IS 14478:2026",
        "title": "Plain bearings",
        "chunk_text": "PRIVATE RETRIEVED PASSAGE",
        "source_url": "https://www.bis.gov.in/know-your-standard",
    }]
    monkeypatch.setattr(assistant, "load_llm_config", lambda: _llm_config())
    monkeypatch.setattr(assistant, "_rag_lookup", lambda *_a, **_kw: (evidence, {"enabled": True}))
    monkeypatch.setattr(rag_llm, "chat_complete", lambda *_a, **_kw: None)

    response = assistant.answer("What does this standard require?", "en")

    assert response["kind"] == "model_unavailable"
    assert "unavailable" in response["text"].lower()
    assert "PRIVATE RETRIEVED PASSAGE" not in response["text"]
    assert not response["sources"] and not response["citations"]


def test_privacy_and_language_helpers():
    assert detect_lang("नल के पानी का मानक?") == "hi"
    assert find_pii("call me 9876543210")["phone"]
    assert "REDACTED" in redact("mail a@b.com ph 9876543210")


def test_consent_store_keeps_its_existing_contract():
    store = ConsentStore()
    assert not store.save_profile("u", {"phone": "9876543210"})
    store.set_consent("u", True)
    assert store.save_profile("u", {"phone": "x", "secret": "drop"})
    assert "secret" not in store.records["u"]["profile"]
    store.delete("u")
    assert "u" not in store.records
