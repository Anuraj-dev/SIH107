"""Safe, structured observability for the RAG-backed chat path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import logging

from fastapi.testclient import TestClient

import bis_assistant.server as srv
from bis_assistant import metrics as metrics_mod


class _RecordHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append({
            "message": record.getMessage(),
            "ctx": getattr(record, "ctx", {}),
        })


def _response(diagnostics=None):
    response = {
        "text": "A model-generated response.",
        "kind": "llm_answer",
        "lang": "en",
        "refused": False,
        "needs_info": False,
        "sources": [],
    }
    if diagnostics is not None:
        response["retrieval_diagnostics"] = diagnostics
    return response


def _post_chat(monkeypatch, tmp_path, answer, query="plastic-bottle-query-secret"):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "ops.db")
    monkeypatch.setattr(srv, "answer", answer)
    metrics_mod.reset()
    return TestClient(srv.app).post("/chat", json={"query": query})


def test_chat_logs_safe_retrieval_details_and_returns_sanitized_diagnostics(
        monkeypatch, tmp_path):
    query_secret = "plastic-bottle-query-secret"
    evidence_secret = "private retrieved chunk contents"
    handler = _RecordHandler()
    srv.log.addHandler(handler)
    try:
        def fake_answer(*_args):
            return _response({
                "branch": "hybrid",
                "selected_count": 1,
                "rejected_count": 1,
                "rejection_reasons": {"below_threshold": 1},
                "retrieval_ms": 17,
                "query": query_secret,
                "debug": {"api_key": "do-not-log-this"},
                "results": [
                    {"rank": 1, "evidence_type": "catalogue_record", "score": 0.81234567,
                     "source_id": "IS 15410:2025", "selected": True,
                     "title": evidence_secret, "chunk_text": evidence_secret},
                    {"rank": 2, "evidence_type": "document_chunk", "score": -0.2,
                     "standard_number": "IS 18474 (Part 5):2026", "selected": False,
                     "rejection_reason": "below_threshold", "text": evidence_secret},
                ],
            })

        response = _post_chat(monkeypatch, tmp_path, fake_answer, query_secret)
    finally:
        srv.log.removeHandler(handler)

    assert response.status_code == 200
    diagnostics = response.json()["retrieval_diagnostics"]
    assert diagnostics == {
        "branch": "hybrid",
        "selected_count": 1,
        "rejected_count": 1,
        "rejection_reasons": {"below_threshold": 1},
        "results": [
            {"evidence_type": "catalogue_record", "rank": 1, "score": 0.812346,
             "source_id": "IS 15410:2025", "selected": True},
            {"evidence_type": "document_chunk", "rank": 2, "score": -0.2,
             "source_id": "IS 18474 (Part 5):2026", "selected": False,
             "rejection_reason": "below_threshold"},
        ],
        "retrieval_ms": 17,
    }

    logged = repr(handler.records)
    for secret in (query_secret, evidence_secret, "do-not-log-this"):
        assert secret not in logged
    result_events = [r["ctx"] for r in handler.records
                     if r["ctx"].get("event") == "rag_retrieval_result"]
    assert [event["rank"] for event in result_events] == [1, 2]
    assert [event["evidence_type"] for event in result_events] == [
        "catalogue_record", "document_chunk"]
    summary = next(r["ctx"] for r in handler.records
                   if r["ctx"].get("event") == "rag_retrieval")
    assert summary["branch"] == "hybrid"
    assert summary["selected_count"] == 1 and summary["rejected_count"] == 1
    assert summary["outcome"] == "answered"
    assert isinstance(summary["latency_ms"], int)

    snapshot = metrics_mod.snapshot()
    assert snapshot["rag_retrieval_total"] == 1
    assert snapshot["rag_retrieval_branch_hybrid_total"] == 1
    assert snapshot["rag_retrieval_selected_total"] == 1
    assert snapshot["rag_retrieval_rejected_total"] == 1
    assert snapshot["rag_retrieval_rejected_reason_below_threshold_total"] == 1
    assert snapshot["rag_retrieval_result_type_catalogue_record_total"] == 1
    assert snapshot["rag_retrieval_result_type_document_chunk_total"] == 1
    assert snapshot["rag_retrieval_outcome_answered_total"] == 1
    assert snapshot["rag_retrieval_latency_p50_ms"] == 17


def test_chat_without_diagnostics_remains_supported(monkeypatch, tmp_path):
    response = _post_chat(monkeypatch, tmp_path, lambda *_args: _response())

    assert response.status_code == 200
    assert "retrieval_diagnostics" not in response.json()
    assert metrics_mod.snapshot().get("rag_retrieval_total", 0) == 0
    prometheus = TestClient(srv.app).get("/metrics").text
    for series in (
        "bis_rag_retrieval_total", "bis_rag_retrieval_selected_total",
        "bis_rag_retrieval_rejected_total", "bis_rag_retrieval_latency_p50_ms",
        "bis_rag_retrieval_latency_p95_ms",
    ):
        assert series in prometheus


def test_unrecognized_diagnostic_values_are_bounded(monkeypatch, tmp_path):
    response = _post_chat(monkeypatch, tmp_path, lambda *_args: _response({
        "branch": "user-supplied arbitrary value",
        "selected_count": 10**20,
        "rejected_count": -4,
        "rejection_reasons": {"sensitive query text": 2},
        "results": [{"rank": 1, "type": "arbitrary", "score": float("inf"),
                     "source_id": "user-supplied query text", "selected": False,
                     "rejection_reason": "sensitive query text"}],
    }))

    assert response.status_code == 200
    diagnostics = response.json()["retrieval_diagnostics"]
    assert diagnostics["branch"] == "other"
    assert diagnostics["selected_count"] == 1_000_000
    assert diagnostics["rejected_count"] == 0
    assert diagnostics["rejection_reasons"] == {"other": 2}
    assert diagnostics["results"] == [{
        "evidence_type": "other", "rank": 1, "selected": False,
        "rejection_reason": "other",
    }]
