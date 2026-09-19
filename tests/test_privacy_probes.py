"""Privacy probes (plan §7/§9): seeded PII must never survive redaction into DB/logs.

CI runs this file explicitly (.github/workflows/ci.yml) — not a regex self-check:
each fixture's raw secret must be absent from stored rows and captured logs.
"""
import io
import json
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from fastapi.testclient import TestClient

import bis_assistant.server as srv
from bis_assistant.i18n_privacy import redact

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / "eval" / "pii_fixtures.json").read_text())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "ops.db")
    with TestClient(srv.app) as c:
        yield c


def test_redact_covers_regex_pii():
    for fx in FIXTURES:
        if fx["type"] in ("phone", "phone_intl", "email", "aadhaar_like"):
            assert fx["raw"] not in redact(fx["query"]), fx


def test_db_stores_no_raw_regex_pii(client):
    raws = [fx["raw"] for fx in FIXTURES
            if fx["type"] in ("phone", "phone_intl", "email", "aadhaar_like")]
    for fx in FIXTURES:
        if fx["type"] not in ("phone", "phone_intl", "email", "aadhaar_like"):
            continue
        client.post("/chat", json={"query": fx["query"]})
    conn = srv._db()
    try:
        blob = "\n".join(r["history_redacted_json"] for r in conn.execute(
            "SELECT history_redacted_json FROM threads").fetchall())
        blob += "\n" + "\n".join(r["text_redacted"] for r in conn.execute(
            "SELECT text_redacted FROM messages").fetchall())
        for raw in raws:
            assert raw not in blob, raw
    finally:
        conn.close()


def test_logs_carry_no_raw_pii(client, caplog):
    fx = next(f for f in FIXTURES if f["type"] == "phone")
    handler = logging.StreamHandler(io.StringIO())
    srv.log.addHandler(handler)
    try:
        with caplog.at_level(logging.INFO, logger="bis.api"):
            client.post("/chat", json={"query": fx["query"]})
        assert fx["raw"] not in handler.stream.getvalue()
        assert fx["raw"] not in caplog.text
    finally:
        srv.log.removeHandler(handler)
