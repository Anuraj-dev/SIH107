"""CLI demo: python -m bis_assistant.cli [--lang en|hi] [--server URL]"""
from __future__ import annotations
import sys
from .chat import chat as chat_turn, ThreadHandle
from .assistant import answer  # noqa: F401 - kept for backward-compat imports
from .i18n_privacy import ConsentStore, redact

store = ConsentStore()


def _remote_ask(base: str, q: str, thread_id, token):
    import json
    import urllib.request
    payload = {"query": q}
    if thread_id:
        payload["thread_id"] = thread_id
    req = urllib.request.Request(base.rstrip("/") + "/chat",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"X-Owner-Token": token} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    lang = None
    server = None
    if "--lang" in sys.argv:
        lang = sys.argv[sys.argv.index("--lang") + 1]
    if "--server" in sys.argv:
        server = sys.argv[sys.argv.index("--server") + 1]
    print("BIS Assistant (MVP)" + (f" via {server}" if server else "")
          + " — type 'quit' to exit, 'new' for a new topic, 'assume' to answer with assumptions.")
    print("If your query lacks detail, I will ask follow-up questions until I have enough context.")
    uid = "demo-user"
    handle: ThreadHandle | None = None
    thread_id, token = None, None
    while True:
        try:
            q = input("\nYou: ").strip()
        except EOFError:
            break
        if q.lower() in ("quit", "exit"):
            break
        if q.lower() in ("new", "new topic"):
            handle = None
            thread_id, token = None, None
            print("Assistant: fresh topic — ask away.")
            continue
        if q.lower().startswith("i consent"):
            store.set_consent(uid, True)
            print("Assistant: consent recorded. Business details will be minimised + deletable.")
            continue
        if "delete my data" in q.lower() or "mera data" in q:
            store.delete(uid)
            print("Assistant: data deleted.")
            continue
        if server:
            try:
                r = _remote_ask(server, q, thread_id, token)
            except Exception as e:
                print(f"Assistant: [server error: {e}]")
                continue
            thread_id = r.get("thread_id")
            token = r.get("owner_token", token)
            print("\nAssistant:\n" + r["text"])
            if r.get("needs_info"):
                print("\n[answer the questions above, or start 'new' topic]")
            continue
        if q.lower() in ("assume", "answer anyway") and handle:
            last_q = handle.history[-1] if handle.history else ""
            if not last_q:
                print("Assistant: nothing to assume on yet — ask a question first.")
                continue
            r = chat_turn(last_q, lang or "auto", thread=handle, force=True)
            handle = r.thread
            print("\nAssistant:\n" + r.text)
            if r.needs_info:
                print("\n[answer the questions above, or type 'assume' / 'new']")
            if any(r.pii.values()):
                print("\n[privacy: PII detected in query — logged redacted only]")
            continue
        r = chat_turn(q, lang or "auto", thread=handle)
        handle = r.thread
        print("\nAssistant:\n" + r.text)
        if r.needs_info:
            print("\n[answer the questions above, or type 'assume' / 'new']")
        if any(r.pii.values()):
            print("\n[privacy: PII detected in query — logged redacted only: " + redact(q)[:80] + "]")


if __name__ == "__main__":
    main()
