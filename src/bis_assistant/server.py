"""Production API (plan §5, Phase 3): FastAPI, server-side threads, owner tokens,
rate limits, request IDs, redacted JSON logs, consent/erasure/export endpoints.

Legacy client-held `context` is accepted as a one-turn migration bridge only:
the server immediately mints a thread_id that clients must use afterwards.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import sys
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
from . import threads as threadmod
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
    hashes = _admin_hashes()
    got = _key_hash(key) if key else ""
    if not key or not hashes or not any(hmac.compare_digest(got, h) for h in hashes):
        raise HTTPException(status_code=403, detail={
            "error": "admin key required", "code": "forbidden", "retryable": False})
    return got[:16]


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


def _touch_bucket(bucket: str, window: float, n: int) -> None:
    now = time.time()
    dq = _hits.setdefault(bucket, deque())
    while dq and dq[0] <= now - window:
        dq.popleft()
    if len(dq) >= n:
        raise HTTPException(status_code=429, detail={
            "error": "rate_limited", "code": "rate_limited", "retryable": True})
    dq.append(now)


def _check_limit(ip: str, api_key: Optional[str], path: str) -> None:
    if api_key and _is_registered(api_key):
        _touch_bucket(f"reg:{api_key}", 3600, CFG["api"]["registered_per_hour"])
        return
    _touch_bucket(f"anon:{ip}", 3600, CFG["api"]["anon_per_hour"])
    if path == "/chat":
        _touch_bucket(f"burst:{ip}", 60, CFG["api"]["anon_burst_per_min"])


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
    context: Optional[dict] = None  # deprecated bridge; thread_id authoritative.
    # One-turn migration only: accepted, truncated to last 4 turns, then the
    # server mints a thread_id clients must use afterwards. New code must
    # pass thread_id (see chat.py ThreadHandle) — context will be removed.
    force: bool = False
    new_topic: bool = False  # Design 3: ignore thread_id/context, mint fresh thread


class ThreadOut(BaseModel):
    thread_id: str
    owner_token: str
    expires_at: str


class ConsentIn(BaseModel):
    user_ref: str = Field(min_length=1, max_length=128)
    purpose: str = "personalise BIS licensing guidance"


app = FastAPI(title="BIS Assistant API", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=CFG["api"]["cors_allow_origins"],
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "X-Owner-Token", "X-User-Ref",
                                  "X-API-Key", "X-Request-ID", "X-Admin-Key"])


@app.middleware("http")
async def _rid(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or secrets.token_hex(8)
    t0 = time.time()
    ip = request.client.host if request.client else "?"
    try:
        if request.url.path not in ("/health", "/metrics"):
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
    stored = row["owner_token_hash"] or ""
    got = _key_hash(token) if token else ""
    if not token or not stored or not hmac.compare_digest(got, stored):
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
        if body.new_topic:
            # Explicit fresh topic: drop any carried state, mint below.
            history, rounds, tid = [], 0, None
        elif tid:
            row = _get_thread(conn, tid)
            if row["owner_token_hash"]:
                _check_owner(row, x_owner_token)
            ctx = threadmod.normalize_context({
                "history": json.loads(row["history_redacted_json"] or "[]"),
                "rounds": row["rounds"]})
            history, rounds = ctx["history"], ctx["rounds"]
        elif isinstance(body.context, dict) and body.context.get("history"):
            log.warning("legacy context bridge used; minting thread_id — "
                        "clients must switch to thread_id",
                        extra={"ctx": {"request_id": request.headers.get("X-Request-ID", "")}})
            ctx = threadmod.normalize_context({
                "history": threadmod.bridge_history(
                    [redact(h)[:2000] for h in body.context["history"]]),
                "rounds": body.context.get("rounds", 0)})
            history, rounds = ctx["history"], ctx["rounds"]
        q = body.query.strip()
        if not q:
            raise HTTPException(status_code=400, detail={
                "error": "empty query", "code": "bad_request", "retryable": False})
        if _wants_erasure(q):
            if not tid:
                raise HTTPException(status_code=400, detail={
                    "error": "owner token + thread required to erase",
                    "code": "bad_request", "retryable": False})
            row = conn.execute("SELECT * FROM threads WHERE id=?", (tid,)).fetchone()
            if row is None:
                raise HTTPException(status_code=410, detail={
                    "error": "unknown thread; start a new topic", "code": "thread_gone",
                    "retryable": False})
            _check_owner(row, x_owner_token)
            out = _erase_thread(conn, tid)
            _audit(conn, "user:" + _key_hash(x_owner_token or tid)[:16], "erasure", "chat")
            return {"text": "Stored messages for this thread were erased.",
                    "refused": False, "kind": "erasure", "lang": "en",
                    "citations": [], "pii": find_pii(q), "needs_info": False,
                    "questions": [], "known": [], "assumptions": [],
                    "context": {"history": [], "rounds": 0},
                    "erased_threads": out["erased_threads"],
                    "thread_id": tid}
        lang = body.lang if body.lang in ("en", "hi") else None
        t0 = time.time()
        resp = answer(q, lang, {"history": history, "rounds": rounds, "force": body.force})
        ms = int((time.time() - t0) * 1000)
        new_history = threadmod.push_history(history, redact(q)[:2000])
        new_rounds = threadmod.rounds_from(resp.get("context"), default=rounds)
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
        log.info("chat response completed", extra={"ctx": {
            "kind": resp.get("kind"), "lang": resp.get("lang"),
            "needs_info": resp.get("needs_info"), "ms": ms,
            "rag_mode": resp.get("rag_mode", ""),
            "rag_used_llm": bool(resp.get("rag_used_llm", False)),
            "source_count": len(resp.get("sources") or resp.get("rag_evidence") or []),
            "pii": [k for k, v in find_pii(q).items() if v],
            "q": redact(q)[:120]}})
        metrics_mod.incr("chat_total")
        metrics_mod.observe_latency_ms(ms)
        if resp.get("kind") == "model_unavailable":
            metrics_mod.incr("model_unavailable_total")
        elif resp.get("refused"):
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


# Chat-side erase: real intent only — not substring "mera data" (data sheet, etc.).
_ERASE_INTENT = re.compile(
    r"(?:delete|erase|remove|wipe)\s+my\s+data|"
    r"mera\s+data\s+(?:mitao|mita\s*do|hatao|hatayen|hata\s*do|delete|erase)|"
    r"(?:mitao|hatao|hatayen)\s+mera\s+data",
    re.I,
)


def _wants_erasure(query: str) -> bool:
    ql = re.sub(r"\s+", " ", (query or "").strip().lower())
    return bool(_ERASE_INTENT.search(ql))


def _erase_thread(conn: sqlite3.Connection, tid: str) -> dict:
    """Capability is the owner token of one thread — never fan out on user_ref."""
    conn.execute("DELETE FROM messages WHERE thread_id=?", (tid,))
    conn.execute("DELETE FROM feedback WHERE thread_id=?", (tid,))
    conn.execute("DELETE FROM threads WHERE id=?", (tid,))
    conn.commit()
    return {"erased_threads": 1}


def _principal_from_owner(conn: sqlite3.Connection, token: Optional[str],
                          x_user_ref: Optional[str]) -> tuple[str, sqlite3.Row]:
    """Owner token is the capability for that thread only; X-User-Ref must match if sent."""
    if not token:
        raise HTTPException(status_code=403, detail={
            "error": "owner token required", "code": "forbidden", "retryable": False})
    row = conn.execute("SELECT * FROM threads WHERE owner_token_hash=?",
                       (_key_hash(token),)).fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail={
            "error": "owner token required", "code": "forbidden", "retryable": False})
    principal = row["user_ref"] or ""
    if x_user_ref and x_user_ref != principal:
        raise HTTPException(status_code=403, detail={
            "error": "owner token does not match user", "code": "forbidden",
            "retryable": False})
    return principal, row


@app.delete("/me")
def erase_me(x_user_ref: Optional[str] = Header(default=None),
             x_owner_token: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        principal, row = _principal_from_owner(conn, x_owner_token, x_user_ref)
        out = _erase_thread(conn, row["id"])
        actor = principal or row["id"]
        _audit(conn, "user:" + _key_hash(actor)[:16], "erasure", "self")
        log.info("erasure", extra={"ctx": {"erased_threads": out["erased_threads"]}})
        return {"user_ref": principal, **out, "sla_hours": CFG["privacy"]["erasure_sla_hours"]}
    finally:
        conn.close()


@app.get("/me/export")
def export_me(x_user_ref: Optional[str] = Header(default=None),
              x_owner_token: Optional[str] = Header(default=None)):
    conn = _db()
    try:
        principal, row = _principal_from_owner(conn, x_owner_token, x_user_ref)
        threads = [dict(row)]
        cons = []
        for t in threads:
            t.pop("owner_token_hash", None)
            t["messages"] = [dict(m) for m in conn.execute(
                "SELECT role, text_redacted, citations_json, kind, ms, created_at"
                " FROM messages WHERE thread_id=? ORDER BY id", (t["id"],)).fetchall()]
        return {"user_ref": principal, "threads": threads, "consents": cons}
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
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from ingest import review as reviewmod
    kconn = kb_store.connect(kb)
    try:
        if body.approve:
            reviewmod.cmd_approve(kconn, body.diff_id, by=f"admin:{pub}")
        else:
            reviewmod.cmd_reject(kconn, body.diff_id)
    except reviewmod.ReviewError as e:
        code = {404: "not_found", 400: "bad_request"}.get(e.http_status, "conflict")
        raise HTTPException(status_code=e.http_status, detail={
            "error": str(e), "code": code, "retryable": False}) from e
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
