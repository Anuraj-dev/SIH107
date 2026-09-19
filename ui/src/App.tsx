import { useCallback, useEffect, useRef, useState } from "react";
import { bisChat, checkHealth, fetchThreadExport, sendFeedback } from "./api";
import { redactPii } from "./redact.mjs";
import AdminPanel from "./admin";
import StandardsDirectory from "./StandardsDirectory";
import SchemesView from "./SchemesView";
import TelemetryView from "./TelemetryView";
import {
  AssumptionsBanner,
  FeedbackButtons,
  KnownChips,
  MetaBadges,
  NoteInput,
  QuestionPills,
  RichText,
  Sources,
  TypingDots,
} from "./components";
import {
  ManakEmblemIcon,
  SidebarToggleIcon,
  ArrowUpRightIcon,
  SunIcon,
  MicIcon,
  CameraIcon,
  PlusIcon,
  ArrowUpIcon,
  CatalogIcon,
  SchemesIcon,
  AuditIcon,
  DiffIcon,
  DownloadIcon,
  XIcon,
} from "./icons";
import type { Lang, Msg } from "./types";
import type { ServerThread } from "./api";
import "./styles.css";

type ViewMode = "chat" | "directory" | "schemes" | "admin" | "telemetry";

const HERO_SUGGESTIONS = [
  {
    label: "What's the standard for packaged drinking water?",
    q: "What is the standard for packaged drinking water (IS 10500 / IS 14543)?",
  },
  {
    label: "How to apply for ISI Mark certification",
    q: "What is the step-by-step procedure to obtain an ISI mark licence under Scheme-I?",
  },
  {
    label: "Which electronics require mandatory CRS?",
    q: "Which electronic and IT goods require mandatory CRS registration under Scheme-II?",
  },
  {
    label: "Steel bar & TMT rebar testing guidelines",
    q: "What standard covers high strength deformed steel bars and wires (IS 1786)?",
  },
];

const LANG_PILLS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "hi", label: "हिंदी" },
  { id: "auto", label: "Auto (Any Language)" },
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [toast, setToast] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
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
    if (view === "chat" && msgs.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [msgs, busy, view]);

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
    inputRef.current?.focus();
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
      else if (res.fixture) showToast("Feedback recorded locally.");
      else showToast("Thank you — feedback submitted for quality evaluation.");
    },
    [msgs, thread, showToast],
  );

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
        // fallback to local transcript
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
    showToast("Saved local redacted transcript.");
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
    <div className={`app-container${darkMode ? " dark-theme" : ""}`}>
      {/* Mobile Backdrop */}
      {sidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Clean Minimal Sidebar */}
      <aside
        className={`clean-sidebar${sidebarOpen ? " open" : ""}${
          sidebarCollapsed ? " collapsed" : ""
        }`}
      >
        <div className="sidebar-top-section">
          <div className="sidebar-brand-row">
            <div className="brand-icon-wrap">
              <ManakEmblemIcon size={26} />
            </div>
            <span className="brand-name-text">मानक AI</span>
            {sidebarOpen && (
              <button
                type="button"
                className="mobile-close-btn"
                onClick={() => setSidebarOpen(false)}
                aria-label="Close navigation"
              >
                <XIcon size={18} />
              </button>
            )}
          </div>

          <button
            type="button"
            className="btn-clean-new-chat"
            onClick={newTopic}
            title="Start new conversation"
          >
            <PlusIcon size={15} />
            <span>New chat</span>
          </button>

          <div className="history-section">
            <div className="history-label">HISTORY</div>
            <div className="history-list">
              {msgs.length > 0 ? (
                <button
                  type="button"
                  className="history-item active"
                  onClick={() => navigateToView("chat")}
                >
                  <span className="history-item-text">
                    {msgs[0]?.text || "Current conversation"}
                  </span>
                </button>
              ) : null}
              <button
                type="button"
                className="history-item"
                onClick={() => {
                  navigateToView("chat");
                  send("What is the standard for packaged drinking water?", { fresh: true });
                }}
              >
                <span className="history-item-text">Drinking water (IS 10500)</span>
              </button>
              <button
                type="button"
                className="history-item"
                onClick={() => {
                  navigateToView("chat");
                  send("What is the step-by-step procedure to obtain an ISI mark licence?", { fresh: true });
                }}
              >
                <span className="history-item-text">ISI Mark Certification</span>
              </button>
              <button
                type="button"
                className="history-item"
                onClick={() => {
                  navigateToView("chat");
                  send("Which electronic and IT goods require mandatory CRS registration under Scheme-II?", { fresh: true });
                }}
              >
                <span className="history-item-text">Electronics CRS Scheme</span>
              </button>
            </div>
          </div>
        </div>

        <div className="sidebar-bottom-section">
          <button
            type="button"
            className={`sidebar-nav-link${view === "directory" ? " active" : ""}`}
            onClick={() => navigateToView("directory")}
          >
            <CatalogIcon size={16} />
            <span>Standards Catalog</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-link${view === "schemes" ? " active" : ""}`}
            onClick={() => navigateToView("schemes")}
          >
            <SchemesIcon size={16} />
            <span>Certification Schemes</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-link${view === "telemetry" ? " active" : ""}`}
            onClick={() => navigateToView("telemetry")}
          >
            <AuditIcon size={16} />
            <span>Audit & Telemetry</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-link${view === "admin" ? " active" : ""}`}
            onClick={() => navigateToView("admin")}
          >
            <DiffIcon size={16} />
            <span>KB Diff Review</span>
          </button>

          <div className="sidebar-user-card">
            <div className="user-avatar-pill">K</div>
            <div className="user-text-wrap">
              <span className="user-title">Kumar Vaibhav</span>
            </div>
            <button
              type="button"
              className="user-action-btn"
              onClick={exportThread}
              title="Export thread as JSON"
              aria-label="Export conversation"
            >
              <DownloadIcon size={14} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Canvas */}
      <div className="clean-main-canvas">
        {/* Top Floating / Minimal Bar */}
        <header className="clean-topbar">
          <div className="topbar-left-zone">
            <button
              type="button"
              className="btn-topbar-icon"
              onClick={() => {
                if (window.innerWidth <= 840) {
                  setSidebarOpen(!sidebarOpen);
                } else {
                  setSidebarCollapsed(!sidebarCollapsed);
                }
              }}
              aria-label="Toggle navigation drawer"
              title="Toggle sidebar"
            >
              <SidebarToggleIcon size={20} />
            </button>
            {view !== "chat" && (
              <button
                type="button"
                className="btn-back-chat"
                onClick={() => navigateToView("chat")}
              >
                ← Back to Assistant
              </button>
            )}
          </div>

          <div className="topbar-right-zone">
            <button
              type="button"
              className="btn-topbar-icon"
              onClick={() => setDarkMode(!darkMode)}
              aria-label="Toggle theme"
              title="Toggle light / dark mode"
            >
              <SunIcon size={20} />
            </button>
          </div>
        </header>

        {/* Dynamic Body Content */}
        <main className="clean-body-content">
          {view === "directory" && (
            <StandardsDirectory onSelectQuery={handleSelectDirectoryQuery} />
          )}

          {view === "schemes" && (
            <SchemesView onSelectQuery={handleSelectDirectoryQuery} />
          )}

          {view === "admin" && (
            <div className="admin-clean-wrap">
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
            <div className="chat-layout-wrap">
              {msgs.length === 0 ? (
                /* Hero Empty State - Exact inspiration from reference */
                <div className="hero-center-container">
                  <div className="hero-emblem-wrap">
                    <ManakEmblemIcon size={46} />
                  </div>
                  <h1 className="hero-headline">
                    Namaste, I'm <span className="hero-bold-name">मानक AI</span>
                  </h1>
                  <p className="hero-subline">
                    Ask me about Indian Standards, ISI mark or CRS schemes, or try one of these:
                  </p>

                  <div className="hero-cards-grid">
                    {HERO_SUGGESTIONS.map((s) => (
                      <button
                        key={s.q}
                        type="button"
                        className="hero-suggestion-card"
                        disabled={busy}
                        onClick={() => send(s.q, { fresh: true })}
                      >
                        <span className="hero-suggestion-label">{s.label}</span>
                        <ArrowUpRightIcon className="hero-suggestion-icon" size={16} />
                      </button>
                    ))}
                  </div>

                  <div className="hero-lang-row">
                    {LANG_PILLS.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`hero-lang-pill${
                          lang === p.id || (lang === "auto" && p.id === "auto") ? " active" : ""
                        }`}
                        onClick={() => setLang(p.id)}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                /* Active Conversation Stream */
                <div className="chat-messages-container">
                  {msgs.map((m) =>
                    m.role === "user" ? (
                      <div key={m.id} className="user-message-row">
                        <div className="user-bubble">
                          <RichText text={m.text} />
                        </div>
                      </div>
                    ) : (
                      <div key={m.id} className="assistant-message-row">
                        <div className="assistant-avatar">
                          <ManakEmblemIcon size={24} />
                        </div>
                        <div className="assistant-content">
                          {m.error ? (
                            <div className="clean-error-card">
                              <p className="error-text">{m.error}</p>
                              <button
                                type="button"
                                className="btn-clean-retry"
                                onClick={() => send(pendingQ)}
                              >
                                Retry
                              </button>
                            </div>
                          ) : (
                            <div className="clean-answer-container">
                              <div className="answer-prose">
                                <RichText text={m.text} />
                              </div>

                              {m.resp?.assumptions && m.resp.assumptions.length > 0 && (
                                <AssumptionsBanner items={m.resp.assumptions} />
                              )}

                              {m.resp?.known && m.resp.known.length > 0 && (
                                <KnownChips known={m.resp.known} />
                              )}

                              {m.resp?.needs_info && (
                                <QuestionPills
                                  questions={m.resp.questions}
                                  disabled={busy}
                                  onPick={(answer) => send(answer)}
                                  onAssume={() => send(pendingQ, { force: true })}
                                  onNewTopic={newTopic}
                                />
                              )}

                              {m.resp?.citations && m.resp.citations.length > 0 && (
                                <Sources items={m.resp.citations} />
                              )}

                              <div className="message-footer-row">
                                <MetaBadges resp={m.resp ?? {}} ms={m.ms} />
                                <FeedbackButtons
                                  value={m.feedback}
                                  disabled={busy}
                                  onRate={(r) => rate(m.id, r)}
                                />
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
                  )}

                  {busy && <TypingDots />}
                  <div ref={bottomRef} />
                </div>
              )}

              {/* Floating Bottom Capsule Composer */}
              <div className="floating-composer-container">
                <form
                  className="floating-capsule"
                  onSubmit={(e) => {
                    e.preventDefault();
                    send(input);
                  }}
                >
                  <button
                    type="button"
                    className="capsule-icon-btn"
                    title="Browse Standards Catalog"
                    onClick={() => navigateToView("directory")}
                    aria-label="Browse Standards Catalog"
                  >
                    <CameraIcon size={18} />
                  </button>

                  <input
                    ref={inputRef}
                    type="text"
                    className="capsule-input-field"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask anything about Indian Standards, ISI mark, CRS..."
                    autoComplete="off"
                  />

                  <button
                    type="button"
                    className="capsule-icon-btn"
                    title="Voice input"
                    onClick={() => showToast("Voice input will be available in future releases.")}
                    aria-label="Voice input"
                  >
                    <MicIcon size={18} />
                  </button>

                  <button
                    type="submit"
                    className={`capsule-send-circle${input.trim() && !busy ? " active" : ""}`}
                    disabled={busy || !input.trim()}
                    aria-label="Send query"
                  >
                    <ArrowUpIcon size={16} />
                  </button>
                </form>
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
