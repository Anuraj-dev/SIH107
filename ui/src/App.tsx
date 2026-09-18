import { useCallback, useEffect, useRef, useState } from "react";
import { checkHealth, sendChat } from "./api";
import { Badge, RichText } from "./components";
import type { Lang, Msg } from "./types";
import type { ServerThread } from "./api";
import "./styles.css";

const SAMPLES: { label: string; q: string; lang: Lang }[] = [
  { label: "Steel bottle → IS", q: "My startup makes vacuum insulated stainless steel water bottle. Which IS?", lang: "auto" },
  { label: "LED + CRS", q: "I manufacture LED bulbs. Which standard and is CRS registration needed?", lang: "auto" },
  { label: "ISI process", q: "Explain ISI mark product certification process for domestic manufacturer", lang: "auto" },
  { label: "HUID verify", q: "How to verify gold jewellery HUID on BIS Care app?", lang: "auto" },
  { label: "Lab for IS 694", q: "How to find testing lab scope for IS 694 on LIMS?", lang: "auto" },
  { label: "नल का पानी (HI)", q: "नल के पानी का मानक कौन सा है?", lang: "auto" },
  { label: "Hinglish", q: "Nal ke peene ke paani ki gunvatta ka manak kaun sa hai?", lang: "auto" },
  { label: "Refusal demo", q: "Guarantee my licence approval please", lang: "auto" },
];

let nextId = 1;

export default function App() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [lang, setLang] = useState<Lang>("auto");
  const [busy, setBusy] = useState(false);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [thread, setThread] = useState<ServerThread | null>(null);
  const [pendingQ, setPendingQ] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const ping = useCallback(async () => {
    setHealthy(await checkHealth());
  }, []);
  useEffect(() => {
    ping();
    const t = setInterval(ping, 10000);
    return () => clearInterval(t);
  }, [ping]);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs]);

  const send = useCallback(
    async (query: string, opts?: { force?: boolean; fresh?: boolean }) => {
      const q = query.trim();
      if (!q || busy) return;
      setBusy(true);
      const useThread = opts?.fresh ? null : thread;
      setPendingQ(q);
      const userMsg: Msg = { id: nextId++, role: "user", text: q };
      setMsgs((m) => [...m, userMsg]);
      setInput("");
      try {
        const { resp, ms, thread: next } = await sendChat(q, lang, useThread, opts?.force ?? false);
        setMsgs((m) => [...m, { id: nextId++, role: "assistant", text: resp.text, resp, ms }]);
        setThread(resp.needs_info ? next : null);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "request failed";
        if (msg.startsWith("Thread expired")) setThread(null);
        setMsgs((m) => [...m, { id: nextId++, role: "assistant", text: "", error: `${msg}. Is the API on :8000?` }]);
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
  }, []);

  const piiFlags = (m: Msg) =>
    m.resp ? Object.entries(m.resp.pii).filter(([, v]) => v).map(([k]) => k) : [];

  return (
    <div className="shell">
      <header className="top">
        <div>
          <h1>BIS Assistant — Test Console</h1>
          <p className="sub">MVP · sources: bis.gov.in Know-Your-Standard only · EN + हिंदी</p>
        </div>
        <div className="health">
          <span className={`pill ${healthy === null ? "unknown" : healthy ? "ok" : "down"}`}>
            {healthy === null ? "checking…" : healthy ? "API :8000 up" : "API down"}
          </span>
          <button className="ghost" onClick={ping}>recheck</button>
        </div>
      </header>

      <section className="samples">
        {SAMPLES.map((s) => (
          <button key={s.label} className="chip" disabled={busy} onClick={() => send(s.q, { fresh: true })} title={s.q}>
            {s.label}
          </button>
        ))}
        <button className="chip new" disabled={busy} onClick={() => { newTopic(); }} title="Drop follow-up context">
          + new topic{thread ? " (thread open)" : ""}
        </button>
      </section>

      <main className="log">
        {msgs.length === 0 && (
          <div className="empty">
            Ask e.g. “steel water bottle which IS?” or try a sample above. Every grounded answer must carry
            an <code>IS:year [status, last-checked] + URL</code> citation; refusals are expected behaviour, not bugs.
          </div>
        )}
        {msgs.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="bubble user"><RichText text={m.text} /></div>
          ) : (
            <div key={m.id} className="bubble bot">
              {m.error ? (
                <div className="error">{m.error}</div>
              ) : (
                <>
                  <div className="meta">
                    {m.resp!.needs_info
                      ? <Badge tone="refuse">needs info · follow-up</Badge>
                      : m.resp!.refused
                        ? <Badge tone="refuse">refused · {m.resp!.kind}</Badge>
                        : <Badge tone="ok">answered · {m.resp!.kind}</Badge>}
                    <Badge tone="lang">{m.resp!.lang === "hi" ? "हिंदी" : "EN"}</Badge>
                    {typeof m.ms === "number" && <span className="ms">{m.ms} ms</span>}
                    {piiFlags(m).length > 0 && <Badge tone="pii">PII: {piiFlags(m).join(", ")}</Badge>}
                  </div>
                  <RichText text={m.text} />
                  {m.resp!.needs_info && (
                    <div className="qs">
                      {m.resp!.questions.map((q) => (
                        <div key={q.slot} className="qcard">
                          <div className="qq">{q.text}</div>
                          <div className="qopts">
                            {q.options.map((o) => (
                              <button key={o.send} className="chip" disabled={busy}
                                onClick={() => send(o.send)}>
                                {o.label}
                              </button>
                            ))}
                            {q.options.length === 0 && <span className="hint">reply in your own words</span>}
                          </div>
                        </div>
                      ))}
                      <div className="qacts">
                        <button className="ghost" disabled={busy}
                          onClick={() => send(pendingQ, { force: true })}>
                          Answer with assumptions
                        </button>
                        <button className="ghost" disabled={busy} onClick={newTopic}>New topic</button>
                      </div>
                    </div>
                  )}
                  {m.resp!.citations.length > 0 && (
                    <div className="cites">
                      <div className="cites-h">Citations ({m.resp!.citations.length})</div>
                      {m.resp!.citations.map((c, i) => <div key={i} className="cite">{c}</div>)}
                    </div>
                  )}
                  {showRaw && <pre className="raw">{JSON.stringify(m.resp, null, 2)}</pre>}
                </>
              )}
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="bar">
        <select value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label="Language">
          <option value="auto">auto</option>
          <option value="en">en</option>
          <option value="hi">hi</option>
        </select>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send(input)}
          placeholder="Type a product or BIS question… (Enter to send)"
        />
        <button className="primary" disabled={busy || !input.trim()} onClick={() => send(input)}>
          {busy ? "…" : "Ask"}
        </button>
        <label className="rawtgl"><input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} /> raw</label>
        <button className="ghost" onClick={() => setMsgs([])}>clear</button>
      </footer>
    </div>
  );
}
