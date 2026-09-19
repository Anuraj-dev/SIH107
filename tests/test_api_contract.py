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
    from bis_assistant import assistant
    monkeypatch.setattr(assistant, "load_llm_config", lambda: {
        "provider": "openai-compatible", "model": "", "api_key": "",
        "base_url": "https://api.openai.com/v1", "retries": 0,
    })
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
    assert d["kind"] == "model_unavailable"
    assert d["model_available"] is False
    assert "unavailable" in d["text"].lower()
    assert d["questions"] == [] and d["citations"] == []
    assert d["thread_id"] and d["owner_token"]
    assert r.headers["X-Request-ID"]


def test_thread_followup_and_read(client):
    t1 = client.post("/chat", json={"query": "steel bottle"}).json()
    t2 = client.post("/chat", json={"query": "vacuum insulated, 1 litre",
                                    "thread_id": t1["thread_id"]},
                     headers={"X-Owner-Token": t1["owner_token"]}).json()
    assert t1["kind"] == t2["kind"] == "model_unavailable"
    assert "IS 17803" not in t2["text"]
    assert t2["thread_id"] == t1["thread_id"]
    got = client.get(f"/threads/{t1['thread_id']}",
                     headers={"X-Owner-Token": t1["owner_token"]}).json()
    assert len(got["messages"]) == 4  # 2 user + 2 assistant


def test_configured_chat_calls_model_for_runtime_questions(client, monkeypatch):
    from bis_assistant import assistant, rag_llm

    calls = []
    cfg = {"provider": "openai-compatible", "model": "test-model", "api_key": "k",
           "base_url": "https://llm.example.test/v1", "retries": 0}
    monkeypatch.setattr(assistant, "load_llm_config", lambda: cfg)
    monkeypatch.setattr(assistant, "_rag_lookup", lambda *_a, **_kw: ([], {"enabled": True}))
    monkeypatch.setattr(rag_llm, "chat_complete",
                        lambda messages, _cfg=None: calls.append(messages) or "MODEL TIME ANSWER")

    response = client.post("/chat", json={"query": "What is the current time?"})

    assert response.status_code == 200
    assert response.json()["text"] == "MODEL TIME ANSWER"
    assert response.json()["model_available"] is True
    assert len(calls) == 1
    assert "current time" in calls[0][1]["content"].lower()


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
    assert t["thread_id"] and t["owner_token"]
    e = client.delete("/me", headers={"X-User-Ref": "u1",
                                      "X-Owner-Token": t["owner_token"]}).json()
    assert e["erased_threads"] == 1
    x = client.get("/me/export", headers={"X-User-Ref": "u1",
                                          "X-Owner-Token": t["owner_token"]})
    assert x.status_code == 403


def test_erasure_requires_owner_token(client):
    assert client.delete("/me").status_code == 403
    assert client.delete("/me", headers={"X-User-Ref": "u1"}).status_code == 403


def test_export_erase_idor(client):
    a = client.post("/chat", json={"query": "cement"},
                    headers={"X-User-Ref": "alice"}).json()
    b = client.post("/chat", json={"query": "steel bottle"},
                    headers={"X-User-Ref": "bob"}).json()
    assert client.get("/me/export", headers={"X-User-Ref": "alice"}).status_code == 403
    assert client.get("/me/export", headers={
        "X-User-Ref": "alice", "X-Owner-Token": b["owner_token"]}).status_code == 403
    assert client.delete("/me", headers={
        "X-User-Ref": "alice", "X-Owner-Token": b["owner_token"]}).status_code == 403
    got = client.get(f"/threads/{a['thread_id']}",
                     headers={"X-Owner-Token": a["owner_token"]})
    assert got.status_code == 200
    exp = client.get("/me/export", headers={"X-Owner-Token": b["owner_token"]})
    assert exp.status_code == 200
    assert exp.json()["user_ref"] == "bob"
    assert all(t["id"] != a["thread_id"] for t in exp.json()["threads"])


def test_spoofed_user_ref_cannot_export_or_erase_victim_thread(client):
    victim = client.post("/chat", json={"query": "cement"},
                         headers={"X-User-Ref": "alice"}).json()
    attacker = client.post("/chat", json={"query": "steel bottle"},
                           headers={"X-User-Ref": "alice"}).json()
    assert victim["thread_id"] != attacker["thread_id"]
    exp = client.get("/me/export", headers={
        "X-User-Ref": "alice", "X-Owner-Token": attacker["owner_token"]})
    assert exp.status_code == 200
    ids = [t["id"] for t in exp.json()["threads"]]
    assert attacker["thread_id"] in ids
    assert victim["thread_id"] not in ids
    erased = client.delete("/me", headers={
        "X-User-Ref": "alice", "X-Owner-Token": attacker["owner_token"]})
    assert erased.status_code == 200
    assert erased.json()["erased_threads"] == 1
    still = client.get(f"/threads/{victim['thread_id']}",
                       headers={"X-Owner-Token": victim["owner_token"]})
    assert still.status_code == 200
    gone = client.get(f"/threads/{attacker['thread_id']}",
                      headers={"X-Owner-Token": attacker["owner_token"]})
    assert gone.status_code == 410


def test_mera_data_sheet_does_not_erase(client):
    t = client.post("/chat", json={"query": "steel bottle"}).json()
    r = client.post("/chat", json={
        "query": "mera data sheet for steel bottle kahan hai",
        "thread_id": t["thread_id"],
    }, headers={"X-Owner-Token": t["owner_token"]})
    assert r.status_code == 200
    assert r.json()["kind"] != "erasure"
    got = client.get(f"/threads/{t['thread_id']}",
                     headers={"X-Owner-Token": t["owner_token"]})
    assert got.status_code == 200


def test_delete_my_data_erases_only_this_thread(client):
    a = client.post("/chat", json={"query": "cement"},
                    headers={"X-User-Ref": "carol"}).json()
    b = client.post("/chat", json={"query": "steel bottle"},
                    headers={"X-User-Ref": "carol"}).json()
    r = client.post("/chat", json={
        "query": "please delete my data",
        "thread_id": b["thread_id"],
    }, headers={"X-Owner-Token": b["owner_token"], "X-User-Ref": "carol"})
    assert r.status_code == 200
    assert r.json()["kind"] == "erasure"
    assert r.json()["erased_threads"] == 1
    assert client.get(f"/threads/{b['thread_id']}",
                      headers={"X-Owner-Token": b["owner_token"]}).status_code == 410
    assert client.get(f"/threads/{a['thread_id']}",
                      headers={"X-Owner-Token": a["owner_token"]}).status_code == 200


def test_machine_readable_404(client):
    r = client.post("/chat", json={"query": ""})
    assert r.status_code in (400, 422)


def test_kb_publish_missing_diff_is_4xx_not_500(client, monkeypatch, tmp_path):
    monkeypatch.setenv("BIS_ADMIN_API_KEYS", "pubk,aprk")
    kb = tmp_path / "bis.db"
    from bis_assistant import kb_store
    kb_store.connect(kb).close()
    monkeypatch.setenv("BIS_KB_PATH", str(kb))
    r = client.post("/kb/publish", json={
        "diff_id": 999, "approve": True,
        "publisher_key": "pubk", "approver_key": "aprk"})
    assert r.status_code == 404
    assert (r.json().get("code") or r.json().get("detail", {}).get("code")) == "not_found"
    rej = client.post("/kb/publish", json={
        "diff_id": 999, "approve": False,
        "publisher_key": "pubk", "approver_key": "aprk"})
    assert rej.status_code == 404
    assert (rej.json().get("code") or rej.json().get("detail", {}).get("code")) == "not_found"


def test_kb_publish_empty_source_url_is_bad_request(client, monkeypatch, tmp_path):
    monkeypatch.setenv("BIS_ADMIN_API_KEYS", "pubk,aprk")
    kb = tmp_path / "bis.db"
    from bis_assistant import kb_store
    conn = kb_store.connect(kb)
    try:
        snap = kb_store.new_snapshot(conn, "test", "x")
        conn.execute(
            "INSERT INTO pending_diffs(snapshot_id, change_type, is_number, details_json, status)"
            " VALUES (?,?,?,?,?)",
            (snap, "added", "IS 8888",
             '{"title_en":"No URL","source_url":"","detail_url":'
             '"https://www.bis.gov.in/know-your-standard/"}',
             "pending"))
        conn.commit()
        did = conn.execute("SELECT id FROM pending_diffs").fetchone()["id"]
    finally:
        conn.close()
    monkeypatch.setenv("BIS_KB_PATH", str(kb))
    r = client.post("/kb/publish", json={
        "diff_id": did, "approve": True,
        "publisher_key": "pubk", "approver_key": "aprk"})
    assert r.status_code == 400
    assert (r.json().get("code") or r.json().get("detail", {}).get("code")) == "bad_request"
