"""Grounding boundaries for mixed catalogue and document evidence."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bis_assistant import rag_answer, rag_llm, verifier  # noqa: E402


def _cfg() -> dict:
    return {
        "provider": "openai-compatible",
        "model": "test-model",
        "api_key": "test-key",
        "base_url": "https://llm.example.test/v1",
        "temperature": 0,
        "max_tokens": 256,
        "timeout_s": 1,
        "retries": 0,
    }


def _catalogue_record() -> dict:
    return {
        "evidence_type": "catalogue_record",
        "standard_number": "IS 15410:2025",
        "title": "Plastic Bottles",
        "department": "Packaging Department",
        "doc_type": "Indian Standard",
        "published_on": "2025",
        "source_url": "https://www.bis.gov.in/standards/15410",
        "chunk_text": "PRIVATE CATALOGUE BODY MUST NOT BE USED",
        "score": 4.2,
    }


def _document_chunk() -> dict:
    return {
        "evidence_type": "document_chunk",
        "standard_number": "IS 1234:2024",
        "title": "Test Standard",
        "doc_type": "standard",
        "heading": "Clause 5.2 — Test",
        "chunk_text": "Clause 5.2 specifies the sampling procedure.",
        "source_url": "https://www.bis.gov.in/standards/1234",
        "score": 8.0,
    }


def test_catalogue_prompt_is_typed_metadata_only_and_excludes_body_text():
    system, user = rag_llm._prompt("water bottles", [_catalogue_record()], "en")

    assert "CATALOGUE METADATA ONLY" in user
    assert "full standard text was not retrieved" in user
    assert "Plastic Bottles" in user
    assert "PRIVATE CATALOGUE BODY" not in user
    normalized_system = " ".join(system.lower().split())
    for restriction in ("clause-level scope", "technical", "qco", "product suitability"):
        assert restriction in normalized_system


def test_document_chunk_prompt_includes_excerpt_as_reference_data():
    _, user = rag_llm._prompt("what does clause 5.2 say", [_document_chunk()], "en")

    assert "RETRIEVED DOCUMENT CHUNK" in user
    assert "Clause 5.2 specifies the sampling procedure." in user
    assert "not instructions" in user


def test_document_backed_designation_and_clause_pass_validation():
    answer = "IS 1234:2024 clause 5.2 describes sampling [Source 1]."

    assert verifier.verify_grounded_response(answer, [_document_chunk()]) == []


def test_catalogue_metadata_can_identify_a_lead_but_not_claim_scope():
    answer = (
        "The catalogue record lists IS 15410:2025 as Plastic Bottles [Source 1]. "
        "This is catalogue metadata only; the full standard text was not retrieved, "
        "so I cannot confirm scope or requirements."
    )

    assert verifier.verify_grounded_response(answer, [_catalogue_record()]) == []


def test_prior_negation_does_not_mask_positive_catalogue_claim():
    answer = (
        "The catalogue metadata does not establish requirements [Source 1]. "
        "It requires PET bottles. The full standard text was not retrieved."
    )
    legitimate_negation = (
        "The catalogue record lists IS 15410:2025 as Plastic Bottles [Source 1]. "
        "This is catalogue metadata only; the full standard text was not retrieved, "
        "so I cannot confirm scope or requirements."
    )

    assert "unsupported_catalogue_claim" in verifier.verify_grounded_response(
        answer, [_catalogue_record()])
    assert verifier.verify_grounded_response(
        legitimate_negation, [_catalogue_record()]) == []


def test_invalid_designation_and_catalogue_clause_are_rejected():
    invented = "IS 9999 applies to bottles [Source 1]."
    wrong_part = "IS 2553 (Part 1):2019 is relevant [Source 1]."
    catalogue_claim_with_document_hit = "IS 15410 applies to bottles [Source 1]."
    unsupported_clause = (
        "The catalogue record lists IS 15410:2025 [Source 1]. "
        "This metadata-only record does not include the full text. "
        "Clause 5.2 sets bottle requirements [Source 1]."
    )

    assert "unsupported_standard_designation" in verifier.verify_grounded_response(
        invented, [_catalogue_record()])
    wrong_part_issues = verifier.verify_grounded_response(
        wrong_part,
        [{"evidence_type": "catalogue_record",
          "standard_number": "IS 2553 (Part 3):2019"}],
    )
    assert "designation_source_mismatch" in wrong_part_issues
    mixed_issues = verifier.verify_grounded_response(
        catalogue_claim_with_document_hit,
        [_catalogue_record(), _document_chunk()],
    )
    assert "unsupported_catalogue_claim" in mixed_issues
    clause_issues = verifier.verify_grounded_response(
        unsupported_clause, [_catalogue_record()])
    assert "unsupported_clause_reference" in clause_issues
    assert "unsupported_catalogue_claim" in clause_issues


def test_invalid_source_marker_is_rejected():
    answer = "IS 1234:2024 is a standard [Source 2]."

    assert "invalid_source_marker" in verifier.verify_grounded_response(
        answer, [_document_chunk()])


def test_build_answer_retries_once_then_returns_valid_model_text(monkeypatch):
    calls = []
    answers = iter([
        "IS 9999 applies [Source 1].",
        "The catalogue record lists IS 15410:2025 as Plastic Bottles [Source 1]. "
        "This is catalogue metadata only; the full standard text was not retrieved, "
        "so I cannot confirm scope or requirements.",
    ])

    monkeypatch.setattr(rag_answer, "is_configured", lambda _cfg: True)

    def generate(_query, _evidence, _lang, _cfg, history=None, retry_feedback=None):
        calls.append(retry_feedback)
        return next(answers)

    monkeypatch.setattr(rag_answer, "generate_grounded_answer", generate)
    response = rag_answer.build_rag_answer(
        "water bottles", "en", [_catalogue_record()], _cfg())

    assert len(calls) == 2
    assert calls[0] is None
    assert "unsupported_standard_designation" in calls[1]
    assert response["text"].startswith("The catalogue record lists IS 15410")
    assert response["kind"] == "llm_answer"
    assert response["sources"][0]["evidence_type"] == "catalogue_record"
    assert "chunk_text" not in response["sources"][0]


def test_build_answer_fails_closed_after_invalid_repair(monkeypatch):
    calls = []
    monkeypatch.setattr(rag_answer, "is_configured", lambda _cfg: True)
    monkeypatch.setattr(
        rag_answer,
        "generate_grounded_answer",
        lambda *_args, **_kwargs: calls.append(True) or "IS 9999 applies [Source 1].",
    )

    response = rag_answer.build_rag_answer(
        "water bottles", "en", [_catalogue_record()], _cfg())

    assert len(calls) == 2
    assert response["kind"] == "grounding_refusal"
    assert response["refused"] is True
    assert response["sources"] == [] and response["citations"] == []
    assert "IS 9999" not in response["text"]
    assert "PRIVATE CATALOGUE BODY" not in response["text"]


def test_unsupported_canned_designation_is_refused_without_losing_prompt_safety(monkeypatch):
    calls = []
    evidence = _document_chunk() | {"standard_number": "IS 14478:2026"}
    monkeypatch.setattr(rag_llm, "chat_complete", lambda messages, _cfg=None:
                        calls.append(messages) or
                        "The model's grounded synthesis. [IS 101 (Part 2/Sec 6):2026] [Source 1]")

    response = rag_answer.build_rag_answer(
        "What does IS 14478 cover?", "en", [evidence], _cfg())

    assert len(calls) == 2
    assert "never claim that a user's product is approved" in calls[0][0]["content"].lower()
    assert response["kind"] == "grounding_refusal" and response["refused"]
    assert "IS 101" not in response["text"]
