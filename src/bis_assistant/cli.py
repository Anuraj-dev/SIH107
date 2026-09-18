"""CLI demo: python -m bis_assistant.cli [--lang en|hi]"""
from __future__ import annotations
import sys
from .assistant import answer
from .i18n_privacy import ConsentStore, redact

store = ConsentStore()


def main():
    lang = None
    if "--lang" in sys.argv:
        lang = sys.argv[sys.argv.index("--lang") + 1]
    print("BIS Assistant (MVP) — type 'quit' to exit, 'new' for a new topic, 'assume' to answer with assumptions.")
    print("If your query lacks detail, I will ask follow-up questions until I have enough context.")
    uid = "demo-user"
    ctx: dict | None = None
    while True:
        try:
            q = input("\nYou: ").strip()
        except EOFError:
            break
        if q.lower() in ("quit", "exit"):
            break
        if q.lower() in ("new", "new topic"):
            ctx = None
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
        if q.lower() in ("assume", "answer anyway") and ctx:
            ctx = {**ctx, "force": True}
            q = ctx.get("history", [""])[-1] if ctx.get("history") else ""
            if not q:
                print("Assistant: nothing to assume on yet — ask a question first.")
                continue
        r = answer(q, lang, ctx)
        ctx = r["context"] or None
        print("\nAssistant:\n" + r["text"])
        if r.get("needs_info"):
            print("\n[answer the questions above, or type 'assume' / 'new']")
        if any(r["pii"].values()):
            print("\n[privacy: PII detected in query — logged redacted only: " + redact(q)[:80] + "]")


if __name__ == "__main__":
    main()
