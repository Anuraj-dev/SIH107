"""SIH-gap fixes: NLU intents, memory, LLM providers, catalogue fallback,
adaptive guidance, translation + vocabulary. See README § "SIH requirement audit".
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RAG_DB = ROOT / "kb" / "bis_rag.db"


def _hermetic(monkeypatch, **env):
    monkeypatch.setenv("BIS_RETRIEVAL_KB_BACKEND", "json")
    from bis_assistant import slots as slotmod
    monkeypatch.setattr(slotmod, "_DB_SLOTS", None)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for v in ("BIS_LLM_MODEL", "BIS_LLM_API_KEY"):
        if v not in env:
            monkeypatch.delenv(v, raising=False)


# --- NLU ---------------------------------------------------------------------

def test_intents_match_journey_routing():
    from bis_assistant import nlu
    cases = {
        "How do I verify HUID on gold jewellery I bought?": "hallmarking",
        "where do I get this tested — find a lab for IS 17803?": "lab_suggestion",
        "I manufacture 9W B22 self-ballasted LED bulbs. Which standard and is CRS needed?": (
            "recommend_standard", "certification_guidance"),
        "IS 10500 year and status — is it active?": "standard_info",
        "How to apply for ISI licence for a new cement plant?": (
            "process_explanation", "certification_guidance"),
    }
    for q, exp in cases.items():
        got = nlu.classify(q)["intent"]
        assert got == exp if isinstance(exp, str) else got in exp, (q, got)


def test_nlu_entities_and_graceful_unknowns():
    from bis_assistant import nlu
    r = nlu.classify("IS 14478 plain bearings scope for a new plant licence?")
    assert "IS 14478" in r["entities"]["is_numbers"]
    assert r["entities"]["stage"] == "new_licence"
    assert "bearings" in r["entities"]["product_terms"]
    g = nlu.classify("xyzzy qwerty zzz")
    assert g["intent"] == "general" and g["confidence"] == "low"
    assert nlu.classify("")["intent"] == "general"


def test_nlu_history_keeps_recommendation_thread():
    from bis_assistant import nlu
    short = nlu.classify("stainless steel bottle, 1 litre",
                         history=["My startup makes water bottle. Which IS?"])
    assert short["scores"]["recommend_standard"] > 0
    assert nlu.classify("1 litre")["scores"]["recommend_standard"] == 0


# --- memory -------------------------------------------------------------------

def test_memory_summary_and_expansion():
    from bis_assistant.memory import expand_query, summarize_thread
    assert summarize_thread([]) == ""
    s = summarize_thread(["My startup makes water bottle. Which IS?",
                          "stainless steel vacuum, 1 litre"])
    assert "water bottle" in s and "vacuum" in s
    assert "vacuum" in expand_query("1 litre for household",
                                    ["My startup makes water bottle. Which IS?",
                                     "stainless steel vacuum"])
    assert expand_query("IS 10500 status?", None) == "IS 10500 status?"


# --- LLM providers --------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload: dict):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _mock_urlopen(monkeypatch, bodies, seen):
    def fake(req, timeout=None):
        seen.append({"url": req.full_url,
                     "data": json.loads(req.data.decode()),
                     "headers": dict(req.header_items())})
        body = bodies[min(len(seen) - 1, len(bodies) - 1)]
        if isinstance(body, Exception):
            raise body
        return _FakeResp(body)
    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_openai_compatible_provider(monkeypatch):
    _hermetic(monkeypatch, BIS_LLM_PROVIDER="openai-compatible",
              BIS_LLM_MODEL="gpt-4o-mini", BIS_LLM_API_KEY="k",
              BIS_LLM_BASE_URL="https://api.openai.com/v1")
    from bis_assistant.rag_llm import chat_complete
    seen = []
    _mock_urlopen(monkeypatch, [{"choices": [{"message": {"content": "hi"}}]}], seen)
    assert chat_complete([{"role": "user", "content": "q"}]) == "hi"
    assert seen[0]["url"].endswith("/chat/completions")
    assert seen[0]["data"]["model"] == "gpt-4o-mini"
    assert "Bearer" in seen[0]["headers"].get("Authorization", "")


def test_gemini_provider(monkeypatch):
    _hermetic(monkeypatch, BIS_LLM_PROVIDER="gemini",
              BIS_LLM_MODEL="gemini-2.0-flash", BIS_LLM_API_KEY="gkey")
    from bis_assistant.rag_llm import chat_complete
    seen = []
    body = {"candidates": [{"content": {"parts": [{"text": "namaste"}]}}]}
    _mock_urlopen(monkeypatch, [body], seen)
    assert chat_complete([{"role": "user", "content": "q"}]) == "namaste"
    assert ":generateContent?key=gkey" in seen[0]["url"]
    assert "gemini-2.0-flash" in seen[0]["url"]


def test_ollama_provider_needs_no_key(monkeypatch):
    _hermetic(monkeypatch, BIS_LLM_PROVIDER="ollama", BIS_LLM_MODEL="llama3")
    from bis_assistant.rag_llm import chat_complete, is_configured, load_llm_config
    assert is_configured(load_llm_config()) is True
    seen = []
    _mock_urlopen(monkeypatch, [{"message": {"content": "local answer"}}], seen)
    assert chat_complete([{"role": "user", "content": "q"}]) == "local answer"
    assert seen[0]["url"].endswith("/api/chat")


def test_llm_retries_then_succeeds(monkeypatch):
    _hermetic(monkeypatch, BIS_LLM_MODEL="m", BIS_LLM_API_KEY="k",
              BIS_LLM_RETRIES="2")
    from bis_assistant.rag_llm import chat_complete
    seen = []
    _mock_urlopen(monkeypatch, [ConnectionError("down"),
                                {"choices": [{"message": {"content": "ok"}}]}], seen)
    assert chat_complete([{"role": "user", "content": "q"}]) == "ok"
    assert len(seen) == 2


def test_llm_unconfigured_returns_none(monkeypatch):
    _hermetic(monkeypatch)
    from bis_assistant.rag_llm import chat_complete
    assert chat_complete([{"role": "user", "content": "q"}]) is None


def test_llm_provider_endpoint_defaults(monkeypatch):
    _hermetic(monkeypatch)
    from bis_assistant.rag_config import load_llm_config
    assert load_llm_config()["base_url"] == "https://api.openai.com/v1"
    monkeypatch.setenv("BIS_LLM_PROVIDER", "gemini")
    assert load_llm_config()["base_url"] == \
        "https://generativelanguage.googleapis.com"
    monkeypatch.setenv("BIS_LLM_PROVIDER", "ollama")
    assert load_llm_config()["base_url"] == "http://localhost:11434"
    monkeypatch.setenv("BIS_LLM_BASE_URL", "http://custom:8080/v1")
    assert load_llm_config()["base_url"] == "http://custom:8080/v1"


# --- catalogue ------------------------------------------------------------------

needs_ragdb = pytest.mark.skipif(not RAG_DB.exists(), reason="kb/bis_rag.db missing")


@needs_ragdb
def test_catalogue_search_finds_novel_standard():
    from bis_assistant.catalogue_search import search_catalogue
    hits = search_catalogue("ENT surgery instruments oesophagoscope Negus specification",
                            db_path=RAG_DB)
    assert hits and hits[0]["standard_number"] == "IS 11319:2026"
    assert hits[0]["relevant"] is True


def _widget_db(tmp_path):
    """Catalogue-only world: one synthetic row, corpus docs on other topics."""
    from bis_assistant.rag_store import connect_rag, now
    from bis_assistant.chunking import chunk_text, clean_text
    db = tmp_path / "widget_rag.db"
    conn = connect_rag(db)
    try:
        conn.execute(
            "INSERT INTO catalogue_standards VALUES (?,?,?,?,?,?,?,?)",
            (99999, "IS 99999:2026", "IS 99999:2026 Galvanized Iron Widgets",
             "Galvanized iron widgets for fencing hardware", "MECHANICAL (MED)",
             "MED 01 - Widgets", "Product Specification", "2026-01-01"))
        raw = ("Bureau of Indian Standards notification about paints and "
               "formaldehyde testing methods for coating materials.")
        cleaned = clean_text(raw)
        cur = conn.execute(
            "INSERT INTO corpus_documents(source_file, standard_id, standard_number,"
            " title, department, committee, doc_type, category, source_url, source_pdf,"
            " source_ref, extraction_method, translation, chars, raw_text, cleaned_text,"
            " imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("Files/paint.txt", 1, "IS 101:2026", "Paints", "CHD", "CHD 1",
             "gazette", "gazette", "https://example.invalid/p", "paint.pdf", "r",
             "m", "t", len(raw), raw, cleaned, now()))
        for ci, ch in enumerate(chunk_text(cleaned)):
            conn.execute(
                "INSERT INTO corpus_chunks(doc_id, chunk_index, chunk_text, heading,"
                " char_start, char_end, token_count, standard_number, doc_type, source_url)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cur.lastrowid, ci, ch["chunk_text"], "", 0, 1, 5,
                 "IS 101:2026", "gazette", "https://example.invalid/p"))
        conn.commit()
    finally:
        conn.close()
    return db


def test_catalogue_fallback_answers_novel_product(tmp_path, monkeypatch):
    db = _widget_db(tmp_path)
    _hermetic(monkeypatch, BIS_RAG_ENABLED="1", BIS_RAG_DB_PATH=str(db))
    from bis_assistant.assistant import answer
    r = answer("Which standard covers galvanized iron widgets for fencing hardware?")
    assert r["kind"] == "catalogue_answer" and not r["refused"]
    assert "IS 99999" in r["text"] and r["citations"]
    assert "Know-Your-Standard" in r["text"]
    assert "Informational only" in r["text"]


def test_catalogue_fallback_keeps_refusals(tmp_path, monkeypatch):
    db = _widget_db(tmp_path)
    _hermetic(monkeypatch, BIS_RAG_ENABLED="1", BIS_RAG_DB_PATH=str(db))
    from bis_assistant.assistant import answer
    g = answer("xyzzy qwerty zzz")
    assert g["refused"] and g["kind"] == "no_source"
    p = answer("My startup make plastic bottle. Which IS?")
    assert p["refused"] and p["kind"] == "coverage_gap"
    # disabled -> curated behaviour preserved (no catalogue invention)
    monkeypatch.setenv("BIS_RAG_ENABLED", "0")
    n = answer("Which standard covers galvanized iron widgets for fencing hardware?")
    assert n["kind"] != "catalogue_answer"
    assert n.get("needs_info") or n["refused"]


# --- adaptive guidance ------------------------------------------------------------

def test_guidance_tailors_certification_answers(monkeypatch):
    _hermetic(monkeypatch)
    from bis_assistant.assistant import answer
    from bis_assistant.verifier import verify, section_map
    from bis_assistant.retriever import retrieve
    r = answer("I manufacture 9W B22 self-ballasted LED bulbs. "
               "Which standard and is CRS needed for a new plant?")
    assert "IS 16102-1" in r["text"] and "CRS" in r["text"]
    assert r.get("guidance_adaptive") is True
    assert "For your situation:" in r["text"]
    assert verify(r, retrieve("led bulb crs")["section_refs"]) == []
    assert r["intent"] in ("recommend_standard", "certification_guidance")


def test_guidance_disabled_by_switch(monkeypatch):
    _hermetic(monkeypatch, BIS_GUIDANCE_ADAPTIVE="0")
    from bis_assistant.assistant import answer
    r = answer("I manufacture 9W B22 self-ballasted LED bulbs. "
               "Which standard and is CRS needed?")
    assert not r.get("guidance_adaptive")
    assert "For your situation:" not in r["text"]
    assert "IS 16102-1" in r["text"]


# --- translation + vocabulary -------------------------------------------------------

def test_translation_falls_back_without_llm(monkeypatch):
    _hermetic(monkeypatch)
    from bis_assistant.translate import translate_text
    assert translate_text("hello", "hi") is None
    assert translate_text("", "hi") is None
    assert translate_text("hello", "xx") is None


def test_translation_uses_configured_llm(monkeypatch):
    _hermetic(monkeypatch, BIS_LLM_MODEL="m", BIS_LLM_API_KEY="k")
    from bis_assistant.translate import translate_text
    seen = []
    _mock_urlopen(monkeypatch, [{"choices": [{"message": {"content": "नमस्ते"}}]}], seen)
    assert translate_text("hello", "hi") == "नमस्ते"
    assert len(seen) == 1


def test_extended_vocabulary_tokens():
    from bis_assistant.retriever import _tokens
    assert "wire" in _tokens("taar") and "bulb" in _tokens("balb")
    assert "helmet" in _tokens("helmat") and "steel" in _tokens("loha")
    assert "wire" in _tokens("तार") and "bulb" in _tokens("बल्ब")
    assert "cement" in _tokens("सीमेंट")


# --- contract -----------------------------------------------------------------------

def test_chat_turn_carries_intent_and_summary(monkeypatch):
    _hermetic(monkeypatch)
    from bis_assistant.chat import chat
    t1 = chat("My startup makes water bottle. Which IS?")
    assert t1.intent
    t2 = chat("stainless steel vacuum, 1 litre", thread=t1.thread)
    assert "IS 17803" in t2.text
    assert t2.context_summary  # memory of the thread so far
    d = t2.to_dict()
    assert d["intent"] and "context_summary" in d
