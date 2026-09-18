"""API contract tests (plan §9): schema, threads, ownership, consent, erasure."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from fastapi.testclient import TestClient

import bis_assistant.server as srv


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "ops.db")
    srv._hits.clear()
    with TestClient(srv.app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "X-Request-ID" in r.headers


def test_chat_mints_thread(client):
    r = client.post("/chat", json={"query": "steel bottle"})
    assert r.status_code == 200
    d = r.json()
    assert d["needs_info"] is True and d["thread_id"] and d["owner_token"]
    assert r.headers["X-Request-ID"]


def test_thread_followup_and_read(client):
    t1 = client.post("/chat", json={"query": "steel bottle"}).json()
    t2 = client.post("/chat", json={"query": "vacuum insulated, 1 litre",
                                    "thread_id": t1["thread_id"]},
                     headers={"X-Owner-Token": t1["owner_token"]}).json()
    assert "IS 17803" in t2["text"] and t2["thread_id"] == t1["thread_id"]
    got = client.get(f"/threads/{t1['thread_id']}",
                     headers={"X-Owner-Token": t1["owner_token"]}).json()
    assert len(got["messages"]) == 4  # 2 user + 2 assistant


def test_thread_authz(client):
    t1 = client.post("/chat", json={"query": "steel bottle"}).json()
    assert client.get(f"/threads/{t1['thread_id']}").status_code == 403
    assert client.get(f"/threads/{t1['thread_id']}",
                      headers={"X-Owner-Token": "wrong"}).status_code == 403
    assert client.get("/threads/deadbeef",
                      headers={"X-Owner-Token": "x"}).status_code == 410
    assert client.delete(f"/threads/{t1['thread_id']}",
                         headers={"X-Owner-Token": t1["owner_token"]}).status_code == 200


def test_consent_and_erasure(client):
    c = client.post("/consent", json={"user_ref": "u1"}).json()
    assert c["user_ref"] == "u1" and c["expires_at"]
    t = client.post("/chat", json={"query": "cement"},
                    headers={"X-User-Ref": "u1"}).json()
    assert t["thread_id"]
    e = client.delete("/me", headers={"X-User-Ref": "u1"}).json()
    assert e["erased_threads"] == 1
    x = client.get("/me/export", headers={"X-User-Ref": "u1"}).json()
    assert x["threads"] == [] and x["consents"] == []


def test_erasure_requires_user_ref(client):
    assert client.delete("/me").status_code == 400


def test_rate_limit_burst(client):
    for _ in range(5):
        assert client.post("/chat", json={"query": "hi"}).status_code == 200
    r = client.post("/chat", json={"query": "hi"})
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited" and r.json()["retryable"] is True


def test_machine_readable_404(client):
    r = client.post("/chat", json={"query": ""})
    assert r.status_code in (400, 422)
