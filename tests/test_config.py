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
