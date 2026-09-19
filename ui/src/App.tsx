import { useCallback, useEffect, useRef, useState } from "react";
import { bisChat, checkHealth, fetchThreadExport, sendFeedback } from "./api";
import { redactPii } from "./redact.mjs";
import AdminPanel from "./admin";
import StandardsDirectory from "./StandardsDirectory";
import SchemesView from "./SchemesView";
import TelemetryView from "./TelemetryView";
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
import {
  BisLogoIcon,
  ChatIcon,
  CatalogIcon,
  SchemesIcon,
  DiffIcon,
  AuditIcon,
  DownloadIcon,
  PlusIcon,
  ArrowUpIcon,
  MenuIcon,
  XIcon,
} from "./icons";
import type { Lang, Msg } from "./types";
import type { ServerThread } from "./api";
import "./styles.css";

type ViewMode = "chat" | "directory" | "schemes" | "admin" | "telemetry";

const SUGGESTIONS: { label: string; sub: string; q: string; category: string }[] = [
  {
    label: "Steel Bottle → IS 17803",
    sub: "Vacuum insulated flask & QCO requirements",
    q: "My startup makes vacuum insulated stainless steel water bottle. Which IS applies?",
    category: "Consumer Goods",
  },
  {
    label: "LED Lamps + CRS Registration",
    sub: "Electronics safety & Scheme-II",
    q: "I manufacture LED bulbs. Which standard and is CRS registration needed?",
    category: "Electronics",
  },
  {
    label: "Gold Jewellery HUID Verification",
    sub: "Hallmarking & BIS Care consumer app",
    q: "How to verify gold jewellery HUID on BIS Care app?",
    category: "Hallmarking",
  },
  {
    label: "नल का पानी (IS 10500)",
    sub: "पीने के पानी का मानक व रासायनिक सीमाएं",
    q: "नल के पानी का मानक कौन सा है?",
    category: "Water & Food",
  },
  {
    label: "Domestic PVC Cables (IS 694)",
    sub: "Building wiring up to 1100V",
    q: "What standard covers flexible PVC domestic building wire up to 1100V?",
    category: "Electrical",
  },
  {
    label: "Plugs & Sockets (IS 1293)",
    sub: "6A and 16A domestic configurations",
    q: "Do domestic 6A and 16A socket outlets require mandatory BIS ISI marking?",
    category: "Electrical",
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
  const [view, setView] = useState<ViewMode>(() => {
    if (typeof window === "undefined") return "chat";
    const hash = window.location.hash.replace(/^#\/?/, "").toLowerCase();
    if (hash === "directory" || hash === "catalog") return "directory";
    if (hash === "schemes") return "schemes";
    if (hash === "admin") return "admin";
    if (hash === "telemetry" || hash === "audit") return "telemetry";
    return "chat";
  });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [toast, setToast] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const toastTimer = useRef<number | null>(null);

  const navigateToView = useCallback((nextView: ViewMode) => {
    setView(nextView);
    setSidebarOpen(false);
    if (typeof window !== "undefined") {
      const targetHash = nextView === "chat" ? "" : `#${nextView}`;
      if (window.location.hash !== targetHash && !(nextView === "chat" && !window.location.hash)) {
        window.location.hash = targetHash;
      }
    }
  }, []);

  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash.replace(/^#\/?/, "").toLowerCase();
      if (hash === "directory" || hash === "catalog") setView("directory");
      else if (hash === "schemes") setView("schemes");
      else if (hash === "admin") setView("admin");
      else if (hash === "telemetry" || hash === "audit") setView("telemetry");
      else setView("chat");
    };
    window.addEventListener("hashchange", handleHash);
    return () => window.removeEventListener("hashchange", handleHash);
  }, []);

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
    if (view === "chat") {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [msgs, busy, view]);

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
        setMsgs((m) => [
          ...m,
          { id: nextId++, role: "assistant", text: resp.text, resp, ms, feedback: null },
        ]);
        setThread(bisChat.shouldKeepThread(resp) ? next : null);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "request failed";
        if (msg.startsWith("Thread expired")) setThread(null);
        const friendly = /HTTP 429/.test(msg)
          ? "Rate limited — please wait a minute and retry."
          : `${msg}. Is the API running on :8000?`;
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
    navigateToView("chat");
    setMsgs([]);
    setSidebarOpen(false);
  }, [navigateToView]);

  const rate = useCallback(
    async (id: number, rating: 1 | -1, note?: string) => {
      const target = msgs.find((m) => m.id === id);
      if (!target?.resp?.thread_id && !thread) {
        setMsgs((m) => m.map((x) => (x.id === id ? { ...x, feedback: rating } : x)));
        return;
      }
      const tid = target?.resp?.thread_id ?? thread?.id ?? "local";
      const ownerToken =
        thread?.id === tid ? thread.token : target?.resp?.owner_token || thread?.token;
      setMsgs((m) => m.map((x) => (x.id === id ? { ...x, feedback: rating } : x)));
      const res = await sendFeedback(tid, rating, ownerToken, note);
      if (!res.ok) showToast(`Feedback failed: ${res.error ?? "request failed"}.`);
      else if (res.fixture) showToast("Feedback recorded locally (backend stub mode).");
      else showToast("Thank you — feedback submitted for BIS quality evaluation.");
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

    // Export server thread if active handle exists, or find most recent assistant message with token
    const lastMsgWithToken = msgs
      .slice()
      .reverse()
      .find((m) => m.resp?.thread_id && m.resp?.owner_token);
    const targetThread: ServerThread | null =
      thread ||
      (lastMsgWithToken?.resp?.thread_id && lastMsgWithToken?.resp?.owner_token
        ? { id: lastMsgWithToken.resp.thread_id, token: lastMsgWithToken.resp.owner_token }
        : null);

    if (targetThread) {
      try {
        const data = await fetchThreadExport(targetThread);
        save(`bis-thread-${targetThread.id}-${stamp}.json`, { ...data, redacted: true, source: "server" });
        showToast("Conversation exported as redacted JSON.");
        return;
      } catch {
        // fall through to local transcript
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
    showToast(
      targetThread
        ? "Server export unavailable — saved local redacted transcript."
        : "Saved local redacted transcript.",
    );
  }, [msgs, thread, showToast]);

  const handleSelectDirectoryQuery = (queryText: string) => {
    navigateToView("chat");
    send(queryText, { fresh: true });
  };

  const activeSessionId =
    thread?.id ||
    msgs
      .slice()
      .reverse()
      .find((m) => m.resp?.thread_id)?.resp?.thread_id;

  return (
    <div className="dashboard-layout">
      <a className="skip" href="#chat-log">
        Skip to conversation
      </a>

      {/* Mobile Backdrop */}
      {sidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Navigation Sidebar */}
      <aside className={`dashboard-sidebar${sidebarOpen ? " open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-logo-wrap">
            <BisLogoIcon className="w-8 h-8 text-indigo-700" />
          </div>
          <div className="brand-text">
            <h1 className="brand-title">BIS Assistant</h1>
            <p className="brand-org">Bureau of Indian Standards</p>
          </div>
          <button
            type="button"
            className="mobile-close-btn"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close navigation menu"
          >
            <XIcon className="w-5 h-5" />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Main Navigation">
          <div className="nav-group-label">WORKSPACE</div>

          <button
            type="button"
            className={`nav-item${view === "chat" ? " active" : ""}`}
            onClick={() => navigateToView("chat")}
          >
            <ChatIcon className="nav-icon" size={17} />
            <span className="nav-label">Standards Assistant</span>
            {msgs.length > 0 && <span className="nav-count">{msgs.length}</span>}
          </button>

          <button
            type="button"
            className={`nav-item${view === "directory" ? " active" : ""}`}
            onClick={() => navigateToView("directory")}
          >
            <CatalogIcon className="nav-icon" size={17} />
            <span className="nav-label">Standards Catalog</span>
          </button>

          <button
            type="button"
            className={`nav-item${view === "schemes" ? " active" : ""}`}
            onClick={() => navigateToView("schemes")}
          >
            <SchemesIcon className="nav-icon" size={17} />
            <span className="nav-label">Certification Schemes</span>
          </button>

          <div className="nav-group-label mt-4">MANAGEMENT & AUDIT</div>

          <button
            type="button"
            className={`nav-item${view === "admin" ? " active" : ""}`}
            onClick={() => navigateToView("admin")}
          >
            <DiffIcon className="nav-icon" size={17} />
            <span className="nav-label">KB Diff & Review</span>
          </button>

          <button
            type="button"
            className={`nav-item${view === "telemetry" ? " active" : ""}`}
            onClick={() => navigateToView("telemetry")}
          >
            <AuditIcon className="nav-icon" size={17} />
            <span className="nav-label">Audit & Telemetry</span>
          </button>
        </nav>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <div className="thread-status-card">
            <div className="thread-status-top">
              <span
                className={`status-dot ${
                  healthy === null ? "unknown" : healthy ? "ok" : "down"
                }`}
                aria-hidden="true"
              />
              <span className="thread-status-title">
                {healthy === null
                  ? "Checking API…"
                  : healthy
                  ? "API Synchronized"
                  : "API Offline"}
              </span>
            </div>
            <div className="thread-id-text">
              {activeSessionId ? `Session: #${activeSessionId.slice(0, 8)}` : "Ready for new inquiry"}
            </div>
          </div>

          <button
            type="button"
            className="btn-new-chat-side"
            onClick={newTopic}
            title="Start new conversation"
          >
            <PlusIcon className="w-4 h-4" size={16} />
            <span>New Consultation</span>
          </button>
        </div>
      </aside>

      {/* Main App Canvas */}
      <div className="main-canvas">
        {/* Top Header */}
        <header className="dashboard-topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="mobile-menu-toggle"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation sidebar"
            >
              <MenuIcon className="w-5 h-5" size={20} />
            </button>
            <div className="view-indicator">
              <span className="view-crumb">Portal</span>
              <span className="view-crumb-sep">/</span>
              <span className="view-tag">
                {view === "chat"
                  ? "Standards Assistant"
                  : view === "directory"
                  ? "Standards Catalog & Directory"
                  : view === "schemes"
                  ? "BIS Certification Schemes"
                  : view === "admin"
                  ? "Knowledge Base Diff Review"
                  : "System Audit & Telemetry"}
              </span>
            </div>
          </div>

          <div className="topbar-right">
            {/* Language Selector */}
            <div className="lang-selector-group">
              <label className="sr-only" htmlFor="lang-sel">
                Answer language
              </label>
              <select
                id="lang-sel"
                className="lang-select"
                value={lang}
                onChange={(e) => setLang(e.target.value as Lang)}
                title="Answer language: Auto-detect, English, or Hindi"
              >
                <option value="auto">🌐 Auto-Detect</option>
                <option value="en">🇬🇧 English (EN)</option>
                <option value="hi">🇮🇳 हिंदी (Hindi)</option>
              </select>
            </div>

            <button
              type="button"
              className="topbar-btn"
              onClick={exportThread}
              title="Export conversation as redacted JSON"
              aria-label="Export conversation as redacted JSON"
            >
              <DownloadIcon className="w-4 h-4" size={16} />
              <span className="btn-text-hide-mobile">Export JSON</span>
            </button>

            <button
              type="button"
              className="topbar-btn-primary"
              onClick={newTopic}
              title="Start fresh topic"
            >
              <PlusIcon className="w-4 h-4" size={16} />
              <span className="btn-text-hide-mobile">New Chat</span>
            </button>
          </div>
        </header>

        {/* Content Body */}
        <main className="dashboard-body">
          {view === "directory" && (
            <StandardsDirectory onSelectQuery={handleSelectDirectoryQuery} />
          )}

          {view === "schemes" && (
            <SchemesView onSelectQuery={handleSelectDirectoryQuery} />
          )}

          {view === "admin" && (
            <div className="admin-view-wrap">
              <button
                type="button"
                className="btn-back-link"
                onClick={() => navigateToView("chat")}
              >
                ← Return to Standards Assistant
              </button>
              <AdminPanel />
            </div>
          )}

          {view === "telemetry" && (
            <TelemetryView
              healthy={healthy}
              thread={thread || (activeSessionId ? { id: activeSessionId, token: "" } : null)}
              onRefreshHealth={ping}
              onExport={exportThread}
              turnCount={msgs.length}
            />
          )}

          {view === "chat" && (
            <div className="chat-interface">
              <div
                className="chat-stream"
                id="chat-log"
                role="log"
                aria-live="polite"
                aria-label="Conversation"
                tabIndex={-1}
              >
                {msgs.length === 0 ? (
                  <div className="hero-dashboard">
                    <div className="hero-seal-badge">
                      <BisLogoIcon className="w-10 h-10 text-indigo-700" />
                    </div>
                    <h2 className="hero-title">Bureau of Indian Standards Assistant</h2>
                    <p className="hero-tagline">
                      मानक पथप्रदर्शक · National Standards & Conformity Assessment Intelligence
                    </p>
                    <p className="hero-desc">
                      Grounded strictly in verified Indian Standards, Gazette notifications, Quality Control Orders (QCOs), and product manuals.
                    </p>

                    {/* Prompts Cards */}
                    <div className="suggestions-grid">
                      {SUGGESTIONS.map((s) => (
                        <button
                          key={s.label}
                          type="button"
                          className="suggestion-card"
                          disabled={busy}
                          onClick={() => send(s.q, { fresh: true })}
                        >
                          <div className="card-cat-tag">{s.category}</div>
                          <div className="card-title-txt">{s.label}</div>
                          <div className="card-desc-txt">{s.sub}</div>
                        </button>
                      ))}
                    </div>

                    {/* Trust banner */}
                    <div className="trust-strip">
                      <div className="trust-item">
                        <span className="trust-dot" />
                        <span>24,000+ Verified Standards</span>
                      </div>
                      <div className="trust-item">
                        <span className="trust-dot" />
                        <span>Allowlisted Retrieval Only</span>
                      </div>
                      <div className="trust-item">
                        <span className="trust-dot" />
                        <span>DPDP Act 2023 Compliant</span>
                      </div>
                      <div className="trust-item">
                        <span className="trust-dot" />
                        <span>Bilingual EN + हिंदी</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  msgs.map((m) =>
                    m.role === "user" ? (
                      <div key={m.id} className="msg user">
                        <div className="bubble-u">
                          <RichText text={m.text} />
                        </div>
                      </div>
                    ) : (
                      <div key={m.id} className="msg bot">
                        <div className="avatar" aria-hidden="true">
                          <span>BIS</span>
                        </div>
                        <div
                          className="content"
                          lang={m.resp?.lang === "hi" ? "hi" : undefined}
                        >
                          {m.error ? (
                            <div className="error-card">
                              <RichText text={m.error} />
                              <button
                                type="button"
                                className="btn-retry"
                                onClick={() => send(pendingQ)}
                              >
                                Retry Request
                              </button>
                            </div>
                          ) : !m.resp ? (
                            <div className="error-card">
                              <RichText text="Empty answer payload received — please retry." />
                            </div>
                          ) : (
                            <div className="answer-card">
                              <MetaBadges resp={m.resp} ms={m.ms} />
                              <div className="answer-body">
                                <RichText text={m.text} />
                              </div>

                              {m.resp.assumptions.length > 0 && (
                                <AssumptionsBanner items={m.resp.assumptions} />
                              )}

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

                              {m.resp.citations.length > 0 && (
                                <Sources items={m.resp.citations} />
                              )}

                              <EvidenceSources
                                items={m.resp.sources ?? m.resp.rag_evidence}
                              />

                              <RawJson data={m.resp} />

                              <div className="feedback-ribbon">
                                <FeedbackButtons
                                  value={m.feedback}
                                  disabled={busy}
                                  onRate={(r) => rate(m.id, r)}
                                />
                                {m.feedback != null && (
                                  <span className="feedback-ack">
                                    Response recorded for evaluation.
                                  </span>
                                )}
                              </div>

                              {m.feedback != null && (
                                <NoteInput
                                  id={String(m.id)}
                                  onSubmit={(note) => rate(m.id, m.feedback ?? 1, note)}
                                />
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    ),
                  )
                )}

                {busy && <TypingDots />}
                <div ref={bottomRef} />
              </div>

              {/* Composer Box */}
              <div className="composer-container">
                <form
                  className="composer-card"
                  onSubmit={(e) => {
                    e.preventDefault();
                    send(input);
                  }}
                >
                  <label className="sr-only" htmlFor="chat-input">
                    Type a product or BIS question
                  </label>
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
                    placeholder="Ask about product compliance, IS codes (e.g. IS 10500), CRS, or hallmarking…"
                    autoComplete="off"
                    style={{ overflowY: input.split("\n").length > 3 ? "auto" : "hidden" }}
                  />
                  <button
                    type="submit"
                    className="btn-composer-send"
                    disabled={busy || !input.trim()}
                    aria-label="Send query"
                  >
                    <ArrowUpIcon className="w-5 h-5" size={18} />
                  </button>
                </form>

                <div className="composer-hints">
                  <span className="key-hint">Press <strong>↵ Enter</strong> to send · <strong>Shift + ↵</strong> for newline</span>
                  <span className="disclaimer-text">
                    Official informational guidance · Verify with licensed BIS lab or official Gazette before commercial production.
                  </span>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {toast && (
        <div className="toast-notification" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
