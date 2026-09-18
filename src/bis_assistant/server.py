"""Production API (plan §5, Phase 3): FastAPI, server-side threads, owner tokens,
rate limits, request IDs, redacted JSON logs, consent/erasure/export endpoints.

Legacy client-held `context` is accepted as a one-turn migration bridge only:
the server immediately mints a thread_id that clients must use afterwards.
"""
from __future__ import annotations
import hashlib
import json
import logging
import secrets
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .assistant import answer
from .config import load as load_config
from .i18n_privacy import find_pii, redact
from . import metrics as metrics_mod

CFG = load_config()
import os as _os
DB_PATH = Path(_os.environ.get("BIS_OPS_DB",
               str(Path(__file__).resolve().parents[2] / "kb" / "ops.db")))

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads(
  id TEXT PRIMARY KEY, user_ref TEXT DEFAULT '', history_redacted_json TEXT DEFAULT '[]',
  rounds INTEGER DEFAULT 0, lang TEXT DEFAULT 'en',
  created_at TEXT, updated_at TEXT, expires_at TEXT, owner_token_hash TEXT);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, role TEXT,
  text_redacted TEXT, citations_json TEXT DEFAULT '[]', kind TEXT DEFAULT '',
  ms INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS consents(
  user_ref TEXT PRIMARY KEY, purpose TEXT, granted_at TEXT, expires_at TEXT, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS users(
  key_hash TEXT PRIMARY KEY, tier TEXT DEFAULT 'registered', created_at TEXT);
CREATE TABLE IF NOT EXISTS profiles(
  user_ref TEXT PRIMARY KEY, fields_json TEXT DEFAULT '{}', updated_at TEXT);
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, message_id INTEGER,
  rating INTEGER, note_redacted TEXT DEFAULT '', user_ref TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', created_at TEXT);
CREATE TABLE IF NOT EXISTS kb_reviews(
  diff_id INTEGER PRIMARY KEY, publisher TEXT, approver TEXT, decided_at TEXT,
  CHECK (publisher <> approver));
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT, target_ref TEXT, at TEXT);
"""

# ---- logging (redacted JSON, request_id) ----
class _JsonFmt(logging.Formatter):
    def format(self, record):
        payload = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "level": record.levelname, "msg": record.getMessage(),
                   **getattr(record, "ctx", {})}
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(_JsonFmt())
log = logging.getLogger("bis.api")
log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False

# ---- rate limiting (in-process; single-instance pilot) ----
_hits: dict[str, deque] = {}
_registered: set[str] = set()


def _admin_hashes() -> set[str]:
    import os
    return {_key_hash(k.strip()) for k in os.environ.get("BIS_ADMIN_API_KEYS", "").split(",") if k.strip()}


def _require_admin(key: Optional[str]) -> str:
    if not key or _key_hash(key) not in _admin_hashes() or not _admin_hashes():
        raise HTTPException(status_code=403, detail={
            "error": "admin key required", "code": "forbidden", "retryable": False})
    return _key_hash(key)[:16]


def _audit(conn: sqlite3.Connection, actor: str, action: str, target: str) -> None:
    conn.execute("INSERT INTO audit_log(actor, action, target_ref, at) VALUES (?,?,?,?)",
                 (actor, action, target, _utcnow().isoformat()))
    conn.commit()


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _is_registered(api_key: str) -> bool:
    h = _key_hash(api_key)
    if h in _registered:
        return True
    try:
        conn = _db()
        try:
            row = conn.execute("SELECT 1 FROM users WHERE key_hash=?", (h,)).fetchone()
        finally:
            conn.close()
        if row:
            _registered.add(h)
            return True
    except Exception:
        pass
    return False


def _check_limit(ip: str, api_key: Optional[str], path: str) -> None:
    now = time.time()
    if api_key and _is_registered(api_key):
        bucket, window, n = f"reg:{api_key}", 3600, CFG["api"]["registered_per_hour"]
    else:
        if path == "/chat":
            bucket, window, n = f"burst:{ip}", 60, CFG["api"]["anon_burst_per_min"]
        else:
            bucket, window, n = f"anon:{ip}", 3600, CFG["api"]["anon_per_hour"]
    dq = _hits.setdefault(bucket, deque())
    while dq and dq[0] <= now - window:
        dq.popleft()
    if len(dq) >= n:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited", "code": "rate_limited", "retryable": True})
    dq.append(now)


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(OPS_SCHEMA)
    return conn


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- models ----
class ChatIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    lang: Optional[str] = None
    thread_id: Optional[str] = None
    context: Optional[dict] = None  # deprecated bridge; thread_id authoritative
    force: bool = False


class ThreadOut(BaseModel):
    thread_id: str
    owner_token: str
    expires_at: str


class ConsentIn(BaseModel):
    user_ref: str = Field(min_length=1, max_length=128)
    purpose: str = "personalise BIS licensing guidance"


app = FastAPI(title="BIS Assistant API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=CFG["api"]["cors_allow_origins"],
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "X-Owner-Token", "X-User-Ref",
                                  "X-API-Key", "X-Request-ID"])


@app.middleware("http")
async def _rid(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or secrets.token_hex(8)
    t0 = time.time()
    ip = request.client.host if request.client else "?"
    try:
        _check_limit(ip, request.headers.get("X-API-Key"), request.url.path)
        resp = await call_next(request)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
        resp = JSONResponse({**detail, "request_id": rid}, status_code=e.status_code)
    ms = int((time.time() - t0) * 1000)
    resp.headers["X-Request-ID"] = rid
    if resp.status_code >= 500 and request.url.path == "/chat":
        metrics_mod.incr("chat_5xx_total")
    log.info(f"{request.method} {request.url.path} -> {resp.status_code} {ms}ms",
             extra={"ctx": {"request_id": rid, "status": resp.status_code, "ms": ms}})
    return resp


def _get_thread(conn: sqlite3.Connection, tid: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=410, detail={
            "error": "unknown thread; start a new topic", "code": "thread_gone",
            "retryable": False})
    if row["expires_at"] and row["expires_at"] < _utcnow().isoformat():
        conn.execute("DELETE FROM messages WHERE thread_id=?", (tid,))
        conn.execute("DELETE FROM threads WHERE id=?", (tid,))
        conn.commit()
        raise HTTPException(status_code=410, detail={
            "error": "thread expired; start a new topic", "code": "thread_expired",
            "retryable": False})
    return row


def _check_owner(row: sqlite3.Row, token: Optional[str]) -> None:
    if not token or _key_hash(token) != (row["owner_token_hash"] or ""):
        raise HTTPException(status_code=403, detail={
            "error": "owner token required", "code": "forbidden", "retryable": False})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/metrics")
def metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(metrics_mod.render_prometheus())


@app.post("/threads", response_model=ThreadOut)
def new_thread(x_user_ref: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        tid, token = secrets.token_hex(8), secrets.token_urlsafe(32)
        exp = (_utcnow() + timedelta(days=CFG["privacy"]["thread_ttl_days"])).isoformat()
        conn.execute("INSERT INTO threads(id, user_ref, created_at, updated_at, expires_at,"
                     " owner_token_hash) VALUES (?,?,?,?,?,?)",
                     (tid, x_user_ref or "", _utcnow().isoformat(), _utcnow().isoformat(),
                      exp, _key_hash(token)))
        conn.commit()
        return {"thread_id": tid, "owner_token": token, "expires_at": exp}
    finally:
        conn.close()


@app.get("/threads/{tid}")
def read_thread(tid: str, x_owner_token: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        row = _get_thread(conn, tid)
        _check_owner(row, x_owner_token)
        msgs = conn.execute("SELECT role, text_redacted, citations_json, kind, ms, created_at"
                            " FROM messages WHERE thread_id=? ORDER BY id", (tid,)).fetchall()
        return {"thread_id": tid, "rounds": row["rounds"], "lang": row["lang"],
                "messages": [dict(m) for m in msgs]}
    finally:
        conn.close()


@app.delete("/threads/{tid}")
def delete_thread(tid: str, x_owner_token: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        _check_owner(_get_thread(conn, tid), x_owner_token)
        conn.execute("DELETE FROM messages WHERE thread_id=?", (tid,))
        conn.execute("DELETE FROM threads WHERE id=?", (tid,))
        conn.commit()
        return {"deleted": tid}
    finally:
        conn.close()


@app.post("/chat")
def chat(body: ChatIn, request: Request,
         x_owner_token: Optional[str] = Header(default=None),
         x_user_ref: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        history, rounds, tid = [], 0, body.thread_id
        if tid:
            row = _get_thread(conn, tid)
            if row["owner_token_hash"]:
                _check_owner(row, x_owner_token)
            history = json.loads(row["history_redacted_json"] or "[]")
            rounds = row["rounds"]
        elif isinstance(body.context, dict) and body.context.get("history"):
            history = [redact(h)[:2000] for h in body.context["history"][-4:]]
            rounds = int(body.context.get("rounds", 0))
        q = body.query.strip()
        if not q:
            raise HTTPException(status_code=400, detail={
                "error": "empty query", "code": "bad_request", "retryable": False})
        lang = body.lang if body.lang in ("en", "hi") else None
        t0 = time.time()
        resp = answer(q, lang, {"history": history, "rounds": rounds, "force": body.force})
        ms = int((time.time() - t0) * 1000)
        new_history = (history + [redact(q)[:2000]])[-6:]
        new_rounds = resp.get("context", {}).get("rounds", rounds)
        if tid is None:  # mint server thread (bridge + fresh turns)
            tid = secrets.token_hex(8)
            token = secrets.token_urlsafe(32)
            exp = (_utcnow() + timedelta(days=CFG["privacy"]["thread_ttl_days"])).isoformat()
            conn.execute("INSERT INTO threads(id, user_ref, history_redacted_json, rounds,"
                         " lang, created_at, updated_at, expires_at, owner_token_hash)"
                         " VALUES (?,?,?,?,?,?,?,?,?)",
                         (tid, x_user_ref or "", json.dumps(new_history), new_rounds,
                          resp.get("lang", "en"), _utcnow().isoformat(),
                          _utcnow().isoformat(), exp, _key_hash(token)))
            resp["owner_token"] = token
            resp["expires_at"] = exp
        else:
            conn.execute("UPDATE threads SET history_redacted_json=?, rounds=?, updated_at=?"
                         " WHERE id=?", (json.dumps(new_history), new_rounds,
                                         _utcnow().isoformat(), tid))
        conn.execute("INSERT INTO messages(thread_id, role, text_redacted, citations_json,"
                     " kind, ms, created_at) VALUES (?,?,?,?,?,?,?)",
                     (tid, "user", redact(q)[:2000], "[]", "user", 0,
                      _utcnow().isoformat()))
        conn.execute("INSERT INTO messages(thread_id, role, text_redacted, citations_json,"
                     " kind, ms, created_at) VALUES (?,?,?,?,?,?,?)",
                     (tid, "assistant", redact(resp["text"])[:8000],
                      json.dumps(resp.get("citations", [])), resp.get("kind", ""),
                      ms, _utcnow().isoformat()))
        conn.commit()
        resp["thread_id"] = tid
        log.info("chat answered", extra={"ctx": {
            "kind": resp.get("kind"), "lang": resp.get("lang"),
            "needs_info": resp.get("needs_info"), "ms": ms,
            "pii": [k for k, v in find_pii(q).items() if v],
            "q": redact(q)[:120]}})
        metrics_mod.incr("chat_total")
        metrics_mod.observe_latency_ms(ms)
        if resp.get("refused"):
            metrics_mod.incr("refused_total")
        else:
            metrics_mod.incr("answered_total")
        if resp.get("needs_info"):
            metrics_mod.incr("needs_info_total")
        return resp
    finally:
        conn.close()


@app.post("/consent")
def consent(body: ConsentIn):
    conn = _db()
    try:
        granted = _utcnow()
        exp = (granted + timedelta(days=CFG["privacy"]["consent_valid_days"])).isoformat()
        conn.execute("INSERT INTO consents(user_ref, purpose, granted_at, expires_at, revoked_at)"
                     " VALUES (?,?,?,?,?) ON CONFLICT(user_ref) DO UPDATE SET purpose=excluded.purpose,"
                     " granted_at=excluded.granted_at, expires_at=excluded.expires_at, revoked_at=NULL",
                     (body.user_ref, body.purpose, granted.isoformat(), exp, None))
        conn.commit()
        return {"user_ref": body.user_ref, "granted_at": granted.isoformat(),
                "expires_at": exp, "purpose": body.purpose}
    finally:
        conn.close()


def _erase_user(conn: sqlite3.Connection, user_ref: str) -> dict:
    tids = [r["id"] for r in conn.execute(
        "SELECT id FROM threads WHERE user_ref=?", (user_ref,)).fetchall()]
    for tid in tids:
        conn.execute("DELETE FROM messages WHERE thread_id=?", (tid,))
    conn.execute("DELETE FROM threads WHERE user_ref=?", (user_ref,))
    conn.execute("DELETE FROM feedback WHERE user_ref=?" + (
        " OR thread_id IN (%s)" % ",".join("?" * len(tids)) if tids else ""),
        [user_ref, *tids])
    conn.execute("DELETE FROM profiles WHERE user_ref=?", (user_ref,))
    conn.execute("DELETE FROM consents WHERE user_ref=?", (user_ref,))
    conn.commit()
    return {"erased_threads": len(tids)}


@app.delete("/me")
def erase_me(x_user_ref: Optional[str] = Header(default=None)):
    if not x_user_ref:
        raise HTTPException(status_code=400, detail={
            "error": "X-User-Ref required", "code": "bad_request", "retryable": False})
    conn = _db()
    try:
        out = _erase_user(conn, x_user_ref)
        _audit(conn, "user:" + _key_hash(x_user_ref)[:16], "erasure", "self")
        log.info("erasure", extra={"ctx": {"erased_threads": out["erased_threads"]}})
        return {"user_ref": x_user_ref, **out, "sla_hours": CFG["privacy"]["erasure_sla_hours"]}
    finally:
        conn.close()


@app.get("/me/export")
def export_me(x_user_ref: Optional[str] = Header(default=None)):
    if not x_user_ref:
        raise HTTPException(status_code=400, detail={
            "error": "X-User-Ref required", "code": "bad_request", "retryable": False})
    conn = _db()
    try:
        threads = [dict(r) for r in conn.execute(
            "SELECT * FROM threads WHERE user_ref=?", (x_user_ref,)).fetchall()]
        for t in threads:
            t.pop("owner_token_hash", None)
            t["messages"] = [dict(m) for m in conn.execute(
                "SELECT role, text_redacted, citations_json, kind, ms, created_at"
                " FROM messages WHERE thread_id=? ORDER BY id", (t["id"],)).fetchall()]
        cons = [dict(r) for r in conn.execute(
            "SELECT * FROM consents WHERE user_ref=?", (x_user_ref,)).fetchall()]
        return {"user_ref": x_user_ref, "threads": threads, "consents": cons}
    finally:
        conn.close()


class FeedbackIn(BaseModel):
    thread_id: str
    rating: int = Field(ge=-1, le=1)
    note: str = Field(default="", max_length=1000)


@app.post("/feedback")
def feedback(body: FeedbackIn, x_owner_token: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        row = _get_thread(conn, body.thread_id)
        if row["owner_token_hash"]:
            _check_owner(row, x_owner_token)
        msg = conn.execute("SELECT id FROM messages WHERE thread_id=? AND role='assistant'"
                           " ORDER BY id DESC LIMIT 1", (body.thread_id,)).fetchone()
        conn.execute("INSERT INTO feedback(thread_id, message_id, rating, note_redacted,"
                     " user_ref, status, created_at) VALUES (?,?,?,?,?,?,?)",
                     (body.thread_id, msg["id"] if msg else None, body.rating,
                      redact(body.note)[:1000], row["user_ref"], "pending",
                      _utcnow().isoformat()))
        conn.commit()
        metrics_mod.incr("feedback_total")
        if body.rating < 0:
            metrics_mod.incr("feedback_neg_total")
        return {"ok": True, "status": "pending"}
    finally:
        conn.close()


@app.get("/kb/diff")
def kb_diff(x_admin_key: Optional[str] = Header(default=None)):
    import os
    admin = _require_admin(x_admin_key)
    kb = os.environ.get("BIS_KB_PATH", str(Path(__file__).resolve().parents[2] / "kb" / "bis.db"))
    from . import kb_store
    conn = kb_store.connect(kb)
    try:
        rows = conn.execute("SELECT * FROM pending_diffs WHERE status='pending' ORDER BY id").fetchall()
        return {"pending": [dict(r) for r in rows], "reviewed_by": admin}
    finally:
        conn.close()


class PublishIn(BaseModel):
    diff_id: int
    approve: bool
    publisher_key: str
    approver_key: str


@app.post("/kb/publish")
def kb_publish(body: PublishIn):
    import os
    pub, appr = _require_admin(body.publisher_key), _require_admin(body.approver_key)
    if pub == appr:
        raise HTTPException(status_code=400, detail={
            "error": "publisher and approver must be distinct", "code": "bad_request",
            "retryable": False})
    kb = os.environ.get("BIS_KB_PATH", str(Path(__file__).resolve().parents[2] / "kb" / "bis.db"))
    from . import kb_store
    from ingest import review as reviewmod
    kconn = kb_store.connect(kb)
    try:
        if body.approve:
            reviewmod.cmd_approve(kconn, body.diff_id, by=f"admin:{pub}")
        else:
            reviewmod.cmd_reject(kconn, body.diff_id)
    finally:
        kconn.close()
    conn = _db()
    try:
        conn.execute("INSERT INTO kb_reviews(diff_id, publisher, approver, decided_at)"
                     " VALUES (?,?,?,?)", (body.diff_id, pub, appr, _utcnow().isoformat()))
        _audit(conn, f"admin:{pub}", f"kb_publish:{body.diff_id}:{body.approve}", str(body.diff_id))
        conn.commit()
        return {"ok": True, "diff_id": body.diff_id, "approved": body.approve}
    finally:
        conn.close()
