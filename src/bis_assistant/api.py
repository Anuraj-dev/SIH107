"""Stdlib-only HTTP API: POST /chat {query, lang?, force?, new_topic?} | GET /health. Run: python -m bis_assistant.api

Legacy client-held ``context`` dict is accepted as a one-turn migration
bridge only (use ``thread_id`` via the FastAPI server for real threads;
see chat.py ThreadHandle). New clients: ``{query, lang?, force?, new_topic?}``.
"""
from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from .assistant import answer

PORT = 8000


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        if self.path == "/health":
            return self._json({"ok": True})
        return self._json({"error": "use POST /chat"}, 404)

    def do_POST(self):
        if self.path != "/chat":
            return self._json({"error": "use POST /chat"}, 404)
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"error": "invalid JSON"}, 400)
        q = (payload.get("query") or "").strip()
        if not q:
            return self._json({"error": "empty query"}, 400)
        ctx = payload.get("context")
        if not isinstance(ctx, dict) or payload.get("new_topic"):
            ctx = None
        if payload.get("force"):
            ctx = {**(ctx or {}), "force": True}
        return self._json(answer(q, payload.get("lang"), ctx))

    def log_message(self, *a):
        pass


def main():
    print(f"BIS Assistant API on http://127.0.0.1:{PORT}  (POST /chat)")
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
