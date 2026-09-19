import { useCallback, useEffect, useRef, useState } from "react";
import { bisChat, checkHealth, fetchThreadExport, sendFeedback } from "./api";
import { redactPii } from "./redact.mjs";
import AdminPanel from "./admin";
import {
  AssumptionsBanner,
  EvidenceSources,
  FeedbackButtons,
  KnownChips,
  MetaBadges,
  NoteInput,
  QuestionPills,
  RawJson,
  RichText,
  Sources,
  TypingDots,
} from "./components";
import type { Lang, Msg } from "./types";
import type { ServerThread } from "./api";
import "./styles.css";

const SUGGESTIONS: { label: string; sub: string; q: string }[] = [
  {
    label: "Steel bottle → IS",
    sub: "Which standard fits a product",
    q: "My startup makes vacuum insulated stainless steel water bottle. Which IS?",
  },
  {
    label: "LED + CRS",
    sub: "Standard and registration need",
    q: "I manufacture LED bulbs. Which standard and is CRS registration needed?",
  },
  {
    label: "HUID verify",
    sub: "Hallmarking guidance",
    q: "How to verify gold jewellery HUID on BIS Care app?",
  },
  {
    label: "नल का पानी",
    sub: "हिंदी में पूछें",
    q: "नल के पानी का मानक कौन सा है?",
  },
];

let nextId = 1;

export default function App() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [lang, setLang] = useState<Lang>("auto");
  const [busy, setBusy] = useState(false);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [thread, setThread] = useState<ServerThread | null>(null);
  const [pendingQ, setPendingQ] = useState("");
  const [view, setView] = useState<"chat" | "admin">("chat");
  const [toast, setToast] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const toastTimer = useRef<number | null>(null);

  const showToast = useCallback((t: string) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 4000);
  }, []);

  const ping = useCallback(async () => {
    setHealthy(await checkHealth());
  }, []);
  useEffect(() => {
    ping();
    const t = setInterval(ping, 30000);
    return () => clearInterval(t);
  }, [ping]);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  // Auto-grow the composer.
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [input]);

  const send = useCallback(
    async (query: string, opts?: { force?: boolean; fresh?: boolean }) => {
      const q = query.trim();
      if (!q || busy) return;
      setBusy(true);
      const useThread = opts?.fresh ? bisChat.newTopic() : thread;
      setPendingQ(q);
      const userMsg: Msg = { id: nextId++, role: "user", text: q };
      setMsgs((m) => [...m, userMsg]);
      setInput("");
      try {
        const { resp, ms, thread: next } = await bisChat.send(q, {
          lang,
          thread: useThread,
          force: opts?.force ?? false,
          fresh: opts?.fresh ?? false,
        });
        setMsgs((m) => [...m, { id: nextId++, role: "assistant", text: resp.text, resp, ms, feedback: null }]);
        setThread(bisChat.shouldKeepThread(resp) ? next : null);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "request failed";
        if (msg.startsWith("Thread expired")) setThread(null);
        const friendly = /HTTP 429/.test(msg)
          ? "Rate limited — please wait a minute and retry."
          : `${msg}. Is the API running?`;
        setMsgs((m) => [...m, { id: nextId++, role: "assistant", text: "", error: friendly }]);
        setHealthy(false);
      } finally {
        setBusy(false);
      }
    },
    [busy, lang, thread],
  );

  const newTopic = useCallback(() => {
    setThread(null);
    setPendingQ("");
    setView("chat");
    setMsgs([]);
  }, []);

  const rate = useCallback(
    async (id: number, rating: 1 | -1, note?: string) => {
      const target = msgs.find((m) => m.id === id);
      if (!target?.resp?.thread_id && !thread) {
        setMsgs((m) => m.map((x) => (x.id === id ? { ...x, feedback: rating } : x)));
        return;
      }
      const tid = target?.resp?.thread_id ?? thread?.id ?? "local";
      const ownerToken = thread?.id === tid ? thread.token : target?.resp?.owner_token || thread?.token;
      setMsgs((m) => m.map((x) => (x.id === id ? { ...x, feedback: rating } : x)));
      const res = await sendFeedback(tid, rating, ownerToken, note);
      if (!res.ok) showToast(`Feedback failed: ${res.error ?? "request failed"}.`);
      else if (res.fixture) showToast("Feedback recorded locally (no live backend).");
    },
    [msgs, thread, showToast],
  );

  /** Download the current thread as redacted JSON, else the local transcript. */
  const exportThread = useCallback(async () => {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const save = (name: string, payload: unknown) => {
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    };
    if (thread) {
      try {
        const data = await fetchThreadExport(thread);
        save(`bis-thread-${thread.id}-${stamp}.json`, { ...data, redacted: true, source: "server" });
        showToast("Conversation exported (redacted).");
        return;
      } catch {
        // fall through to the local transcript
      }
    }
    save(`bis-thread-local-${stamp}.json`, {
      redacted: true,
      source: "local-transcript",
      exported_at: new Date().toISOString(),
      messages: msgs.map((m) => ({
        role: m.role,
        text: redactPii(m.text),
        kind: m.resp?.kind ?? (m.error ? "error" : "user"),
        lang: m.resp?.lang ?? null,
        citations: m.resp?.citations ?? [],
      })),
    });
    showToast(thread ? "Server export unavailable — saved the local transcript (redacted)." : "Saved the local transcript (redacted).");
  }, [msgs, thread, showToast]);

  return (
    <div className="app">
      <a className="skip" href="#chat-log">Skip to conversation</a>
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">B</span>
          <div className="brand-t">
            <div className="brand-name">BIS Assistant</div>
            <div className="brand-sub">Indian Standards · EN + हिंदी</div>
          </div>
        </div>
        <div className="top-actions">
          <span
            className={`status-dot ${healthy === null ? "unknown" : healthy ? "ok" : "down"}`}
            role="status"
            aria-hidden="true"
          />
          <span className="sr-only" role="status">
            {healthy === null ? "Checking API status" : healthy ? "API connected" : "API unreachable"}
          </span>
          <label className="sr-only" htmlFor="lang-sel">Answer language</label>
          <select
            id="lang-sel"
            className="langsel"
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
            title="Answer language: auto-detect, English, or Hindi"
          >
            <option value="auto">Auto</option>
            <option value="en">EN</option>
            <option value="hi">हिंदी</option>
          </select>
          <button type="button" className="btn" onClick={newTopic}>+ New chat</button>
          <button
            type="button" className="icon-btn" onClick={exportThread}
            title="Export conversation (redacted JSON)" aria-label="Export conversation as redacted JSON"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" x2="12" y1="15" y2="3" />
            </svg>
          </button>
          <button
            type="button" className={`icon-btn${view === "admin" ? " active" : ""}`}
            onClick={() => setView(view === "admin" ? "chat" : "admin")}
            title="Admin diff review" aria-label="Admin diff review" aria-pressed={view === "admin"}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>
      </header>

      {view === "admin" ? (
        <main className="wrap narrow">
          <button type="button" className="link-btn back" onClick={() => setView("chat")}>← Back to chat</button>
          <AdminPanel />
        </main>
      ) : (
        <>
          <main className="thread wrap" id="chat-log" role="log" aria-live="polite" aria-label="Conversation" tabIndex={-1}>
            {msgs.length === 0 ? (
              <div className="hero">
                <h1>What standard does your product need?</h1>
                <p>Ask in plain English or Hindi — every answer cites its BIS source.</p>
                <div className="suggest">
                  {SUGGESTIONS.map((s) => (
                    <button key={s.label} type="button" className="sug" disabled={busy}
                      onClick={() => send(s.q, { fresh: true })}>
                      <span className="sug-t">{s.label}</span>
                      <span className="sug-s">{s.sub}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              msgs.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="msg user">
                    <div className="bubble-u"><RichText text={m.text} /></div>
                  </div>
                ) : (
                  <div key={m.id} className="msg bot">
                    <div className="avatar" aria-hidden="true">B</div>
                    <div className="content" lang={m.resp?.lang === "hi" ? "hi" : undefined}>
                      {m.error ? (
                        <div className="error">
                          <RichText text={m.error} />
                          <button type="button" className="link-btn" onClick={() => send(pendingQ)}>
                            Retry
                          </button>
                        </div>
                      ) : !m.resp ? (
                        <div className="error">
                          <RichText text="Empty answer payload — please retry." />
                        </div>
                      ) : (
                        <>
                          <MetaBadges resp={m.resp} ms={m.ms} />
                          <RichText text={m.text} />
                          {m.resp.assumptions.length > 0 && <AssumptionsBanner items={m.resp.assumptions} />}
                          <KnownChips known={m.resp.known} />
                          {m.resp.needs_info && (
                            <QuestionPills
                              questions={m.resp.questions}
                              disabled={busy}
                              onPick={(answer) => send(answer)}
                              onAssume={() => send(pendingQ, { force: true })}
                              onNewTopic={newTopic}
                            />
                          )}
                          {m.resp.citations.length > 0 && <Sources items={m.resp.citations} />}
                          <EvidenceSources items={m.resp.sources ?? m.resp.rag_evidence} />
                          <RawJson data={m.resp} />
                          <div className="fbrow">
                            <FeedbackButtons value={m.feedback} disabled={busy} onRate={(r) => rate(m.id, r)} />
                            {m.feedback != null && <span className="hint">Thanks for the feedback.</span>}
                          </div>
                          {m.feedback != null && (
                            <NoteInput id={String(m.id)} onSubmit={(note) => rate(m.id, m.feedback ?? 1, note)} />
                          )}
                        </>
                      )}
                    </div>
                  </div>
                ),
              )
            )}
            {busy && <TypingDots />}
            <div ref={bottomRef} />
          </main>

          <footer className="composer-zone wrap">
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
            >
              <label className="sr-only" htmlFor="chat-input">Type a product or BIS question</label>
              <textarea
                id="chat-input"
                ref={taRef}
                rows={1}
                value={input}
                lang={lang === "hi" ? "hi" : undefined}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(input);
                  }
                }}
                placeholder="Ask about a product, standard, or BIS process…"
                autoComplete="off"
              />
              <button type="submit" className="send" disabled={busy || !input.trim()} aria-label="Send message">
                ↑
              </button>
            </form>
            <p className="fine">Informational only — always confirm with BIS or a licensed lab.</p>
          </footer>
        </>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
