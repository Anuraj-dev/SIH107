import React, { useState } from "react";
import type { Question } from "./types";
import {
  AlertTriangleIcon,
  CheckIcon,
  CopyIcon,
  ExternalLinkIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "./icons";

/** Inline markdown: **bold** + auto-linked https:// URLs. No deps, no HTML injection. */
const URL_RE = /(https?:\/\/[^\s)<\]]+)/g;

export function renderInline(body: string, keyPrefix: string): React.ReactNode[] {
  const boldParts = body.split("**");
  const out: React.ReactNode[] = [];
  boldParts.forEach((chunk, bi) => {
    if (bi % 2 === 1) {
      out.push(
        <strong key={`${keyPrefix}-b${bi}`} className="font-semibold text-slate-900">
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
    const trail = url.match(/[.,;!?)\]]+$/);
    let suffix = "";
    if (trail) {
      suffix = trail[0];
      url = url.slice(0, -suffix.length);
    }
    if (m.index > last) {
      out.push(<React.Fragment key={`${keyPrefix}-${k++}`}>{chunk.slice(last, m.index)}</React.Fragment>);
    }
    out.push(
      <a
        key={`${keyPrefix}-${k++}`}
        href={url}
        target="_blank"
        rel="noreferrer"
        className="rlink inline-flex items-center gap-0.5"
      >
        <span>{url}</span>
        <ExternalLinkIcon className="link-ext-icon" />
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

/** Structured reply renderer: headings, numbered items, nested bullets, callouts, dividers, links. */
export function RichText({ text }: { text: string | null | undefined }) {
  const lines = (text ?? "").split("\n");
  const nodes: React.ReactNode[] = [];
  let prevGap = true;

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
          <span className="n" aria-hidden="true">{m[1]}</span>
          <span className="num-body">{renderInline(m[2], `n${i}`)}</span>
        </div>,
      );
      return;
    }
    if ((m = trimmed.match(BULLET_RE))) {
      const isWarn = /^(warning|note)\s*:/i.test(m[1]);
      nodes.push(
        <div key={i} className={`line bullet lvl-${lvl}${isWarn ? " warn" : ""}`}>
          <span className="dot" aria-hidden="true">•</span>
          <span className="bullet-body">{renderInline(m[1], `b${i}`)}</span>
        </div>,
      );
      return;
    }
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

  return <div className="prose-container">{nodes}</div>;
}

/** Server-provided `known[]` rendered as clean parameter chips. */
export function KnownChips({ known }: { known: { slot: string; value: string }[] }) {
  if (!known || known.length === 0) return null;
  return (
    <div className="known" aria-label="Identified parameters">
      <div className="known-title">Identified Parameters:</div>
      <ul className="known-list">
        {known.map((k) => (
          <li key={k.slot} className="known-chip">
            <span className="chip-k">{k.slot}</span>
            <span className="chip-sep">:</span>
            <span className="chip-v">{k.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Server-provided `assumptions[]` rendered as an official caution card. */
export function AssumptionsBanner({ items }: { items: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="assume" role="note" aria-label="Answer uses assumptions">
      <div className="assume-header">
        <AlertTriangleIcon className="assume-icon" />
        <strong>Answer generated with assumed parameters</strong>
      </div>
      <p className="assume-sub">Please confirm these parameters with BIS or an approved lab:</p>
      <ul>
        {items.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </div>
  );
}

/** Strict citations live here — always attached to the answer. */
export function Sources({ items }: { items: string[] | null | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <details className="sources">
      <summary>
        <span className="sources-summary-title">Official BIS Standards Citations</span>
        <span className="sources-count">{items.length}</span>
      </summary>
      <ul>
        {items.map((c, i) => (
          <li key={i} className="source-item">
            <div className="source-content">{renderInline(c, `src${i}`)}</div>
          </li>
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

/** RAG / Gazette / Manual evidence behind an answer. */
export function EvidenceSources({ items }: { items: EvidenceItem[] | null | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <details className="sources evidence">
      <summary>
        <span className="sources-summary-title">Full-Text Corpus Passages</span>
        <span className="sources-count">{items.length}</span>
      </summary>
      <ul>
        {items.map((e, i) => (
          <li key={i} className="ev-card">
            <div className="ev-head">
              <span className="ev-standard">{e.standard_number || "BIS Document"}</span>
              {e.title && <span className="ev-title"> — {e.title}</span>}
              {e.doc_type && <span className="ev-badge">{e.doc_type}</span>}
              <span className="ev-score">Score: {typeof e.score === "number" ? e.score.toFixed(2) : e.score}</span>
            </div>
            {e.heading && <div className="ev-heading">Section: {e.heading}</div>}
            {e.chunk_text && (
              <blockquote className="ev-quote">
                “{e.chunk_text.slice(0, 320)}{e.chunk_text.length > 320 ? "…" : ""}”
              </blockquote>
            )}
            {e.url && /^https?:\/\//i.test(e.url) ? (
              <div className="ev-link">
                <a href={e.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">
                  <span>View official BIS document</span>
                  <ExternalLinkIcon className="link-ext-icon" />
                </a>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Answer metadata badges: kind, language, intent, RAG mode, latency, refusal, PII. */
export function MetaBadges({
  resp,
  ms,
}: {
  resp: {
    kind?: string;
    lang?: string;
    refused?: boolean;
    intent?: string;
    intent_confidence?: string;
    rag_mode?: string;
    rag_used_llm?: boolean;
    pii?: Record<string, boolean>;
  };
  ms?: number;
}) {
  const piiHits = Object.entries(resp.pii ?? {}).filter(([, v]) => v).map(([k]) => k);
  return (
    <div className="meta-row" aria-label="Answer metadata">
      {resp.kind ? <span className="badge info">{resp.kind.replace(/_/g, " ")}</span> : null}
      {resp.lang ? (
        <span className="badge lang">
          {resp.lang === "hi" ? "हिंदी (HI)" : "ENGLISH (EN)"}
        </span>
      ) : null}
      {resp.intent ? (
        <span className="badge info" title={`confidence: ${resp.intent_confidence ?? "low"}`}>
          intent: {resp.intent}
        </span>
      ) : null}
      {resp.rag_mode ? (
        <span
          className="badge ok"
          title={
            resp.rag_used_llm
              ? "Synthesized by configured LLM from retrieved gazette passages"
              : "Deterministic extractive answer directly from indexed standard"
          }
        >
          {resp.rag_used_llm ? "LLM-grounded" : "extractive"}
        </span>
      ) : null}
      {typeof ms === "number" ? <span className="badge speed">{ms} ms</span> : null}
      {resp.refused ? <span className="badge refuse">Refusal / Scope Guard</span> : null}
      {piiHits.length > 0 ? (
        <span className="badge pii">DPDP Redacted: {piiHits.join(", ")}</span>
      ) : null}
    </div>
  );
}

/** Raw response JSON inspector with copy functionality. */
export function RawJson({ data }: { data: unknown }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <details className="rawjson">
      <summary>
        <span className="rawjson-summary-title">Inspect Raw API Response</span>
        <button
          type="button"
          className="rawjson-copy-btn"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            handleCopy();
          }}
          aria-label="Copy raw JSON payload"
        >
          {copied ? (
            <>
              <CheckIcon className="w-3 h-3 text-emerald-400" />
              <span>Copied</span>
            </>
          ) : (
            <>
              <CopyIcon className="w-3 h-3" />
              <span>Copy JSON</span>
            </>
          )}
        </button>
      </summary>
      <pre className="rawjson-code">{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

/** Clarifying questions as clean, interactive action cards. */
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
      <div className="qs-header">
        <span className="qs-label">Clarification Required</span>
        <span className="qs-hint">Select an option to identify the exact standard:</span>
      </div>
      {questions.map((q) => (
        <div key={q.slot} className="q-card">
          <div className="qq">{q.text}</div>
          <div className="qopts">
            {q.options.map((o) => (
              <button
                key={o.send}
                type="button"
                className="pill-btn"
                disabled={disabled}
                onClick={() => onPick(o.send)}
              >
                {o.label}
              </button>
            ))}
            {q.options.length === 0 && <span className="hint">Reply in your own words in the chat box</span>}
          </div>
        </div>
      ))}
      <div className="qacts">
        <button type="button" className="btn-secondary-sm" disabled={disabled} onClick={onAssume}>
          Answer with assumptions
        </button>
        <span className="qacts-sep" aria-hidden="true">·</span>
        <button type="button" className="btn-secondary-sm" disabled={disabled} onClick={onNewTopic}>
          Start new inquiry
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
        className={`fb-btn${value === 1 ? " active-pos" : ""}`}
        aria-label="Helpful answer"
        aria-pressed={value === 1}
        disabled={disabled}
        onClick={() => onRate(1)}
        title="Helpful compliance guidance"
      >
        <ThumbsUpIcon className="w-4 h-4" />
      </button>
      <button
        type="button"
        className={`fb-btn${value === -1 ? " active-neg" : ""}`}
        aria-label="Unhelpful answer"
        aria-pressed={value === -1}
        disabled={disabled}
        onClick={() => onRate(-1)}
        title="Unhelpful or inaccurate guidance"
      >
        <ThumbsDownIcon className="w-4 h-4" />
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
      <label className="sr-only" htmlFor={inputId}>
        Optional feedback note
      </label>
      <input
        id={inputId}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Add context for BIS evaluators (no personal data)…"
        maxLength={500}
      />
      <button type="submit" className="btn-submit-note" disabled={!note.trim()}>
        Submit Note
      </button>
    </form>
  );
}

/** Animated typing indicator when querying. */
export function TypingDots() {
  return (
    <div className="msg bot">
      <div className="avatar" aria-hidden="true">
        <span>BIS</span>
      </div>
      <div className="content">
        <div className="typing-indicator" aria-hidden="true">
          <span className="dot" />
          <span className="dot" />
          <span className="dot" />
          <span className="typing-label">Consulting BIS metadata & gazettes…</span>
        </div>
        <span className="sr-only">Assistant is retrieving standard metadata</span>
      </div>
    </div>
  );
}
