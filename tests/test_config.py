import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant.config import load


def test_defaults():
    cfg = load("/nonexistent.yaml")
    assert cfg["retrieval"]["direct_score"] == 15.0
    assert cfg["privacy"]["retention_days"] == 90


def test_env_override(monkeypatch):
    monkeypatch.setenv("BIS_RETRIEVAL_DIRECT_SCORE", "12.5")
    monkeypatch.setenv("BIS_API_ANON_PER_HOUR", "60")
    cfg = load("/nonexistent.yaml")
    assert cfg["retrieval"]["direct_score"] == 12.5
    assert cfg["api"]["anon_per_hour"] == 60


def test_load_rag_config_min_gates(monkeypatch):
    monkeypatch.setenv("BIS_RAG_MIN_OVERLAP", "9")
    monkeypatch.setenv("BIS_RAG_MIN_LEXICAL", "21.5")
    monkeypatch.setenv("BIS_RAG_CATALOGUE_MIN_SCORE", "12.5")
    from bis_assistant.rag_config import load_rag_config
    from bis_assistant.assistant import _rag_thresholds
    cfg = load_rag_config()
    assert cfg["min_overlap"] == 9
    assert cfg["min_lexical"] == 21.5
    assert cfg["catalogue_min_score"] == 12.5
    th = _rag_thresholds()
    assert th["min_overlap"] == 9
    assert th["min_lexical"] == 21.5
    assert th["catalogue_min_score"] == 12.5
