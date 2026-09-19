"""Stdlib api.py: thread contract, body cap, Content-Length validation."""
import http.client
import json
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bis_assistant import api as apimod  # noqa: E402


@pytest.fixture()
def stdlib_server(monkeypatch):
    apimod._THREADS.clear()
    from bis_assistant import assistant
    monkeypatch.setattr(assistant, "load_llm_config", lambda: {
        "provider": "openai-compatible", "model": "", "api_key": "",
        "base_url": "https://api.openai.com/v1", "retries": 0,
    })
    httpd = HTTPServer(("127.0.0.1", 0), apimod.H)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    host, port = httpd.server_address
    yield host, port
    httpd.shutdown()
    t.join(timeout=2)


def _post(host, port, body, headers=None, raw=None, extra_headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=30)
    hdrs = {"Content-Type": "application/json"}
    if extra_headers:
        hdrs.update(extra_headers)
    if headers:
        hdrs.update(headers)
    payload = raw if raw is not None else json.dumps(body).encode()
    conn.request("POST", "/chat", body=payload, headers=hdrs)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    try:
        parsed = json.loads(data.decode())
    except Exception:
        parsed = data.decode()
    return r.status, parsed


def test_thread_followup_stays_offline_without_model(stdlib_server):
    host, port = stdlib_server
    st, d1 = _post(host, port, {"query": "steel bottle"})
    assert st == 200
    assert d1.get("thread_id") and d1.get("owner_token")
    assert d1.get("kind") == "model_unavailable"
    assert d1.get("questions") == []
    st, d2 = _post(host, port,
                   {"query": "vacuum insulated, 1 litre",
                    "thread_id": d1["thread_id"]},
                   extra_headers={"X-Owner-Token": d1["owner_token"]})
    assert st == 200
    assert d2["thread_id"] == d1["thread_id"]
    assert d2["kind"] == "model_unavailable"
    assert "IS 17803" not in d2["text"]


def test_wrong_owner_token_forbidden(stdlib_server):
    host, port = stdlib_server
    _, d1 = _post(host, port, {"query": "steel bottle"})
    st, _ = _post(host, port,
                  {"query": "1 litre", "thread_id": d1["thread_id"]},
                  extra_headers={"X-Owner-Token": "nope"})
    assert st == 403


def test_invalid_content_length(stdlib_server):
    host, port = stdlib_server
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.putrequest("POST", "/chat")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", "abc")
    conn.endheaders()
    conn.send(b'{"query":"hi"}')
    r = conn.getresponse()
    body = json.loads(r.read().decode())
    conn.close()
    assert r.status == 400
    assert "Content-Length" in body.get("error", "")


def test_body_cap(stdlib_server):
    host, port = stdlib_server
    blob = json.dumps({"query": "x" * (apimod.MAX_BODY)}).encode()
    assert len(blob) > apimod.MAX_BODY
    st, d = _post(host, port, None, raw=blob)
    assert st == 400
    assert "large" in str(d).lower()
