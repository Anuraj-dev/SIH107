import React, { useState } from "react";
import type { Question } from "./types";

/** Inline markdown: **bold** + auto-linked https:// URLs. No deps, no HTML injection. */
const URL_RE = /(https?:\/\/[^\s)<\]]+)/g;

function renderInline(body: string, keyPrefix: string): React.ReactNode[] {
  const boldParts = body.split("**");
  const out: React.ReactNode[] = [];
  boldParts.forEach((chunk, bi) => {
    if (bi % 2 === 1) {
      // Bold span — still linkify inside in case a URL was bolded.
      out.push(
        <strong key={`${keyPrefix}-b${bi}`}>
          {linkifyChunk(chunk, `${keyPrefix}-b${bi}`)}
        </strong>,
      );
      return;
    }
    out.push(...linkifyChunk(chunk, `${keyPrefix}-t${bi}`));
  });
  return out;
}

function linkifyChunk(chunk: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  URL_RE.lastIndex = 0;
  let k = 0;
  while ((m = URL_RE.exec(chunk)) !== null) {
    let url = m[1];
    // Don't swallow trailing punctuation into the link.
    const trail = url.match(/[.,;!?)\]]+$/);
    let suffix = "";
    if (trail) {
      suffix = trail[0];
      url = url.slice(0, -suffix.length);
    }
    if (m.index > last) out.push(<React.Fragment key={`${keyPrefix}-${k++}`}>{chunk.slice(last, m.index)}</React.Fragment>);
    out.push(
      <a key={`${keyPrefix}-${k++}`} href={url} target="_blank" rel="noreferrer" className="rlink">
        {url}
      </a>,
    );
    if (suffix) out.push(<React.Fragment key={`${keyPrefix}-${k++}`}>{suffix}</React.Fragment>);
    last = m.index + m[1].length;
  }
  if (last < chunk.length) out.push(<React.Fragment key={`${keyPrefix}-${k++}`}>{chunk.slice(last)}</React.Fragment>);
  return out;
}

const NUM_RE = /^(\d+)[.)]\s+(.*)$/;
const BULLET_RE = /^[-*•–—]\s+(.*)$/;
const HEADING_RE = /^#{1,3}\s+(.*)$/;
const BOLD_LINE_RE = /^\*\*(.+?)\*\*\s*$/;
const DIVIDER_RE = /^(---|\*\*\*|___)\s*$/;
const QUOTE_RE = /^>\s?(.*)$/;

/** Structured reply renderer: headings, numbered questions, nested bullets, notes, dividers, links. */
export function RichText({ text }: { text: string | null | undefined }) {
  const lines = (text ?? "").split("\n");
  const nodes: React.ReactNode[] = [];
  let prevGap = true; // collapse leading blank lines
  lines.forEach((ln, i) => {
    const trimmed = ln.trim();
    if (trimmed === "") {
      if (!prevGap) {
        nodes.push(<div key={i} className="gap" aria-hidden="true" />);
        prevGap = true;
      }
      return;
    }
    prevGap = false;
    if (DIVIDER_RE.test(trimmed)) {
      nodes.push(<hr key={i} className="rdiv" />);
      prevGap = true;
      return;
    }
    const leading = ln.length - ln.trimStart().length;
    const lvl = Math.min(2, Math.floor(leading / 2));
    let m: RegExpMatchArray | null;
    if ((m = trimmed.match(HEADING_RE))) {
      nodes.push(<div key={i} className="line h">{renderInline(m[1], `h${i}`)}</div>);
      return;
    }
    if ((m = trimmed.match(BOLD_LINE_RE))) {
      nodes.push(<div key={i} className="line h">{renderInline(m[1], `h${i}`)}</div>);
      return;
    }
    if ((m = trimmed.match(QUOTE_RE))) {
      nodes.push(<div key={i} className="line quote">{renderInline(m[1], `q${i}`)}</div>);
      return;
    }
    if ((m = trimmed.match(NUM_RE))) {
      nodes.push(
        <div key={i} className={`line num lvl-${lvl}`}>
          <span className="n" aria-hidden="true">{m[1]}.</span>
          <span>{renderInline(m[2], `n${i}`)}</span>
        </div>,
      );
      return;
    }
    if ((m = trimmed.match(BULLET_RE))) {
      const isWarn = /^(warning|note)\s*:/i.test(m[1]);
      nodes.push(
        <div key={i} className={`line bullet lvl-${lvl}${isWarn ? " warn" : ""}`}>
          <span className="dot" aria-hidden="true">•</span>
          <span>{renderInline(m[1], `b${i}`)}</span>
        </div>,
      );
      return;
    }
    // Section labels ("Candidate standards:", "Still to confirm:", "Terms:", ...)
    // and callouts ("Note: ...", "Warning: ...") get their own emphasis.
    if (/^(note|warning)\s*:/i.test(trimmed)) {
      nodes.push(<div key={i} className="line note">{renderInline(trimmed, `c${i}`)}</div>);
      return;
    }
    if (trimmed.length <= 90 && trimmed.endsWith(":")) {
      nodes.push(<div key={i} className="line label">{renderInline(trimmed, `l${i}`)}</div>);
      return;
    }
    nodes.push(<div key={i} className={`line lvl-${lvl}`}>{renderInline(ln.trim(), `p${i}`)}</div>);
  });
  return <>{nodes}</>;
}

/** Server-provided `known[]` rendered as subtle "known so far" chips. */
export function KnownChips({ known }: { known: { slot: string; value: string }[] }) {
  if (!known || known.length === 0) return null;
  return (
    <div className="known" aria-label="Known so far">
      <ul className="known-list">
        {known.map((k) => (
          <li key={k.slot} className="known-chip">{k.slot} = {k.value}</li>
        ))}
      </ul>
    </div>
  );
}

/** Server-provided `assumptions[]` rendered as a compact notice. */
export function AssumptionsBanner({ items }: { items: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="assume" role="note" aria-label="Answer uses assumptions">
      <strong>Answering with assumptions</strong> — please confirm these with BIS:
      <ul>
        {items.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </div>
  );
}

/** Strict citations live here — one click away, always attached to the answer. */
export function Sources({ items }: { items: string[] | null | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <details className="sources">
      <summary>Sources ({items.length})</summary>
      <ul>
        {items.map((c, i) => (
          <li key={i}>{renderInline(c, `src${i}`)}</li>
        ))}
      </ul>
    </details>
  );
}

export interface EvidenceItem {
  standard_number: string;
  title: string;
  url: string;
  doc_type: string;
  heading: string;
  chunk_text: string;
  chunk_index: number;
  source_file: string;
  score: number;
}

/** RAG/catalogue evidence behind an answer (issue #4 P1-12). */
export function EvidenceSources({ items }: { items: EvidenceItem[] | null | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <details className="sources evidence">
      <summary>Evidence passages ({items.length})</summary>
      <ul>
        {items.map((e, i) => (
          <li key={i}>
            <strong>{e.standard_number || "BIS document"}</strong>
            {e.title ? ` — ${e.title}` : ""}
            {e.doc_type ? <span className="ev-meta"> [{e.doc_type}]</span> : null}
            {e.heading ? <div className="ev-meta">Section: {e.heading}</div> : null}
            {e.chunk_text ? <div className="ev-meta">“{e.chunk_text.slice(0, 280)}{e.chunk_text.length > 280 ? "…" : ""}”</div> : null}
            {e.url ? (
              <div>
                <a href={e.url} target="_blank" rel="noreferrer">Source link</a>
                <span className="ev-meta"> · score {e.score}</span>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Answer metadata badges: kind, language, intent, RAG mode, latency, refusal, PII. */
export function MetaBadges({ resp, ms }: {
  resp: {
    kind?: string; lang?: string; refused?: boolean;
    intent?: string; intent_confidence?: string;
    rag_mode?: string; rag_used_llm?: boolean;
    pii?: Record<string, boolean>;
  };
  ms?: number;
}) {
  const piiHits = Object.entries(resp.pii ?? {}).filter(([, v]) => v).map(([k]) => k);
  return (
    <div className="meta-row" aria-label="Answer metadata">
      {resp.kind ? <span className="badge info">{resp.kind}</span> : null}
      {resp.lang ? <span className="badge lang">{resp.lang.toUpperCase()}</span> : null}
      {resp.intent ? (
        <span className="badge info" title={`confidence ${resp.intent_confidence ?? "low"}`}>
          intent: {resp.intent}
        </span>
      ) : null}
      {resp.rag_mode ? (
        <span className="badge ok" title={resp.rag_used_llm ? "written by the configured LLM from retrieved passages" : "deterministic extractive answer"}>
          {resp.rag_used_llm ? "LLM-grounded" : "extractive"}
        </span>
      ) : null}
      {typeof ms === "number" ? <span className="badge info">{ms} ms</span> : null}
      {resp.refused ? <span className="badge refuse">refused</span> : null}
      {piiHits.length > 0 ? (
        <span className="badge pii">PII redacted: {piiHits.join(", ")}</span>
      ) : null}
    </div>
  );
}

/** Raw response JSON for debugging/verification (issue #4 P1-12). */
export function RawJson({ data }: { data: unknown }) {
  return (
    <details className="rawjson">
      <summary>Raw JSON</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

/** Clarifying questions as tappable pills (multi-turn grounding). */
export function QuestionPills({
  questions,
  disabled,
  onPick,
  onAssume,
  onNewTopic,
}: {
  questions: Question[];
  disabled?: boolean;
  onPick: (send: string) => void;
  onAssume: () => void;
  onNewTopic: () => void;
}) {
  if (!questions || questions.length === 0) return null;
  return (
    <div className="qs">
      {questions.map((q) => (
        <div key={q.slot} className="q">
          <div className="qq">{q.text}</div>
          <div className="qopts">
            {q.options.map((o) => (
              <button key={o.send} type="button" className="pill-btn" disabled={disabled}
                onClick={() => onPick(o.send)}>
                {o.label}
              </button>
            ))}
            {q.options.length === 0 && <span className="hint">Reply in your own words</span>}
          </div>
        </div>
      ))}
      <div className="qacts">
        <button type="button" className="link-btn" disabled={disabled} onClick={onAssume}>
          Answer with assumptions
        </button>
        <span aria-hidden="true">·</span>
        <button type="button" className="link-btn" disabled={disabled} onClick={onNewTopic}>
          New topic
        </button>
      </div>
    </div>
  );
}

export function FeedbackButtons({
  value,
  disabled,
  onRate,
}: {
  value: 1 | -1 | null | undefined;
  disabled?: boolean;
  onRate: (rating: 1 | -1) => void;
}) {
  return (
    <div className="fb" role="group" aria-label="Rate this answer">
      <button
        type="button"
        className={`fb-btn${value === 1 ? " active" : ""}`}
        aria-label="Helpful answer"
        aria-pressed={value === 1}
        disabled={disabled}
        onClick={() => onRate(1)}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M7 10v12" />
          <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
        </svg>
      </button>
      <button
        type="button"
        className={`fb-btn${value === -1 ? " active" : ""}`}
        aria-label="Unhelpful answer"
        aria-pressed={value === -1}
        disabled={disabled}
        onClick={() => onRate(-1)}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M17 14V2" />
          <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
        </svg>
      </button>
    </div>
  );
}

export function NoteInput({
  id,
  onSubmit,
}: {
  id: string;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  const inputId = `fb-note-${id}`;
  return (
    <form
      className="noteform"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(note.trim());
        setNote("");
      }}
    >
      <label className="sr-only" htmlFor={inputId}>Optional feedback note</label>
      <input
        id={inputId}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Add a note (optional, no personal details)…"
        maxLength={500}
      />
      <button type="submit" className="link-btn" disabled={!note.trim()}>Send</button>
    </form>
  );
}

/** Animated dots shown while the assistant is answering. */
export function TypingDots() {
  return (
    <div className="msg bot">
      <div className="avatar" aria-hidden="true">B</div>
      <div className="dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <span className="sr-only">Assistant is typing</span>
    </div>
  );
}
