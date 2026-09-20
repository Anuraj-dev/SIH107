"""LLM title helper tests (pure functions only — no network)."""
from bis_assistant.titles import clean_title, generate_title


def test_clean_title_strips_quotes_and_punctuation():
    assert clean_title('"IS 10500 status?"') == "IS 10500 status"


def test_clean_title_removes_em_dashes():
    assert "—" not in clean_title("Steel grades — Fe415 vs Fe550")
    assert clean_title("Steel grades — Fe415 vs Fe550") == "Steel grades Fe415 vs Fe550"


def test_clean_title_rejects_meta_phrases():
    assert clean_title("Question about cement") == ""
    assert clean_title("Chat about steel") == ""


def test_clean_title_truncates_at_word_boundary():
    long_title = "Drinking water packaging standards and certification process stages"
    out = clean_title(long_title)
    assert len(out) <= 48
    assert not out.endswith(" ")


def test_clean_title_rejects_empty():
    assert clean_title("") == ""
    assert clean_title(None) == ""
    assert clean_title("x") == ""


def test_generate_title_uses_llm_when_configured(monkeypatch):
    import bis_assistant.titles as titles
    import bis_assistant.rag_llm as rag_llm

    monkeypatch.setattr(rag_llm, "is_configured", lambda cfg: True)
    monkeypatch.setattr(rag_llm, "chat_complete",
                        lambda messages, cfg: '"Drinking Water Packaging Standard"')
    out = titles.generate_title("What is the standard for packaging drinking water?",
                                "IS 10500 covers drinking water.")
    assert out == "Drinking Water Packaging Standard"


def test_generate_title_rejects_empty_user_text():
    assert generate_title("") is None
    assert generate_title("   ") is None
