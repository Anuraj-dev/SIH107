import React, { useEffect, useRef, useState } from "react";
import type { Question } from "./types";
import {
  AlertTriangleIcon,
  CheckIcon,
  ChevronDownIcon,
  CopyIcon,
  ExternalLinkIcon,
  ManakEmblemIcon,
  XIcon,
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
        className="rlink"
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

/** True when the user prefers reduced motion (typewriter + animations off). */
export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduce(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduce;
}

/** Structured reply renderer: headings, numbered items, nested bullets, callouts, dividers, links. */
export function RichText({ text }: { text: string | null | undefined }) {
  const segments = splitCodeSegments(text ?? "");
  return (
    <div className="prose-container">
      {segments.map((seg, si) =>
        seg.code ? (
          <pre key={`c${si}`} className="rcode">
            <code>{seg.body.join("\n")}</code>
          </pre>
        ) : (
          <React.Fragment key={`p${si}`}>{renderProseLines(seg.body, `s${si}`)}</React.Fragment>
        ),
      )}
    </div>
  );
}

function splitCodeSegments(text: string): { code: boolean; body: string[] }[] {
  const segments: { code: boolean; body: string[] }[] = [];
  let cur: { code: boolean; body: string[] } = { code: false, body: [] };
  text.split("\n").forEach((ln) => {
    if (ln.trimStart().startsWith("```")) {
      segments.push(cur);
      cur = { code: !cur.code, body: [] };
      return;
    }
    cur.body.push(ln);
  });
  segments.push(cur);
  return segments.filter((s, i) => s.body.length > 0 || i === segments.length - 1);
}

function renderProseLines(lines: string[], keyPrefix: string): React.ReactNode[] {
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

  return nodes;
}

/** Copy-to-clipboard button with transient confirmation. */
export function CopyButton({ text, label = "Copy response" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  const handleCopy = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      setCopied(true);
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button
      type="button"
      className={`icon-btn${copied ? " copied" : ""}`}
      onClick={handleCopy}
      aria-label={label}
      title={copied ? "Copied" : label}
    >
      {copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
    </button>
  );
}

/** Typewriter reveal for freshly arrived assistant text (full text when reduced motion). */
export function TypewriterText({ text }: { text: string }) {
  const reduce = useReducedMotion();
  const [n, setN] = useState(() => (reduce ? text.length : 0));
  useEffect(() => {
    if (reduce) {
      setN(text.length);
      return;
    }
    setN(0);
    if (!text) return;
    const step = Math.max(2, Math.ceil(text.length / 140));
    const t = window.setInterval(() => {
      setN((v) => {
        if (v >= text.length) {
          window.clearInterval(t);
          return v;
        }
        return Math.min(text.length, v + step);
      });
    }, 16);
    return () => window.clearInterval(t);
  }, [text, reduce]);
  return (
    <span className="typewriter">
      <RichText text={text.slice(0, n)} />
    </span>
  );
}

/** Server-provided `known[]` rendered as clean parameter chips. */
export function KnownChips({ known }: { known: { slot: string; value: string }[] }) {
  if (!known || known.length === 0) return null;
  return (
    <div className="known" role="group" aria-label="Identified parameters">
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

/** Strip model source markers so the answer stays readable. */
export function cleanAnswerText(text: string): string {
  let s = text.replace(/\s*\[Source\s*\d+\]/gi, "");
  s = s.replace(/\s*\[IS[^\]]*\]/g, "");
  s = s.replace(/\s*,\s*,/g, ",");
  s = s.replace(/\s*,\s*\./g, ".");
  s = s.replace(/\(\s*\)/g, "");
  s = s.replace(/[ \t]{2,}/g, " ");
  s = s.replace(/ +\n/g, "\n");
  return s.trim();
}

function parseCitationLine(raw: string): { standard: string; title: string } | null {
  const stdMatch = raw.match(/\bIS[\s\d()\/,A-Za-z.:-]+?(?=:|\s[-–]|\s\[|$)/);
  const standard = (stdMatch ? stdMatch[0] : "").trim();
  let title = raw;
  if (standard) title = title.replace(standard, "");
  title = title.replace(/https?:\/\/\S+/g, "").replace(/\[[^\]]*\]/g, "");
  title = title.replace(/^[:\s,-]+/, "").replace(/,\s*Source:?.*$/i, "").trim();
  if (!standard && !title) return null;
  return { standard: standard || "BIS document", title };
}

function pillLabel(standard: string): string {
  const t = standard.replace(/\s+/g, " ").trim();
  return t.length > 18 ? `${t.slice(0, 17)}…` : t;
}

type SourceChip = {
  key: string;
  standard: string;
  title: string;
  heading: string;
  docType: string;
  excerpt: string;
  sourceFile: string;
};

function chipsFromEvidence(items: EvidenceItem[]): SourceChip[] {
  const out: SourceChip[] = [];
  const seen = new Set<string>();
  for (const e of items) {
    const standard = (e.standard_number || "").trim() || "BIS document";
    const id = (e.source_file || "").trim() || `${standard}|${e.chunk_index}`;
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({
      key: id,
      standard,
      title: (e.title || "").trim(),
      heading: (e.heading || "").trim(),
      docType: (e.doc_type || "").trim(),
      excerpt: (e.chunk_text || "").trim(),
      sourceFile: (e.source_file || "").trim(),
    });
    if (out.length >= 5) break;
  }
  return out;
}

function chipsFromCitations(items: string[]): SourceChip[] {
  const out: SourceChip[] = [];
  const seen = new Set<string>();
  for (const raw of items) {
    const parsed = parseCitationLine(raw);
    if (!parsed) continue;
    if (seen.has(parsed.standard)) continue;
    seen.add(parsed.standard);
    out.push({
      key: parsed.standard,
      standard: parsed.standard,
      title: parsed.title,
      heading: "",
      docType: "",
      excerpt: "",
      sourceFile: "",
    });
    if (out.length >= 5) break;
  }
  return out;
}

const EXCERPT_PREVIEW = 280;

function SourceExcerpt({ text }: { text: string }) {
  const [full, setFull] = useState(false);
  const long = text.length > EXCERPT_PREVIEW;
  const shown = !long || full ? text : `${text.slice(0, EXCERPT_PREVIEW).trimEnd()}…`;
  return (
    <>
      <p className="src-page-excerpt">{shown}</p>
      {long && (
        <button type="button" className="src-expand" onClick={() => setFull((v) => !v)}>
          {full ? "Show less" : "Show more"}
        </button>
      )}
    </>
  );
}

/** One bundled source control. Click opens a right-side accordion of our corpus. */
export function SourceStrip({
  sources,
  citations,
}: {
  sources?: EvidenceItem[] | null;
  citations?: string[] | null;
}) {
  const chips =
    sources && sources.length > 0
      ? chipsFromEvidence(sources)
      : chipsFromCitations(citations ?? []);
  const [open, setOpen] = useState(false);
  const [compact, setCompact] = useState(true);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (chips.length === 0) return null;

  const bundleLabel =
    chips.length === 1 ? pillLabel(chips[0].standard) : `${chips.length} sources`;

  const openPanel = () => {
    setOpen(true);
    window.history.replaceState(null, "", "#/sources");
  };

  const closePanel = () => {
    setOpen(false);
    if (window.location.hash.startsWith("#/source")) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  };

  return (
    <>
      <button
        type="button"
        className="src-trigger"
        onClick={openPanel}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={chips.map((c) => c.standard).join(", ")}
      >
        <ManakEmblemIcon size={16} />
        <span className="src-trigger-label">{bundleLabel}</span>
      </button>
      {open && (
        <div className="src-page" role="dialog" aria-modal="true" aria-labelledby="src-page-title">
          <button type="button" className="src-page-scrim" onClick={closePanel} aria-label="Close sources" />
          <div className={`src-page-panel${compact ? " compact" : ""}`}>
            <div className="src-page-top">
              <div id="src-page-title" className="src-page-std">
                {chips.length === 1 ? "Source" : "Sources"}
              </div>
              <div className="src-page-actions">
                <button
                  type="button"
                  className="src-mode"
                  onClick={() => setCompact((v) => !v)}
                  aria-pressed={compact}
                >
                  {compact ? "Comfortable" : "Compact"}
                </button>
                <button type="button" className="icon-btn" onClick={closePanel} aria-label="Close">
                  <XIcon size={16} />
                </button>
              </div>
            </div>
            <div className="src-acc-list">
              {chips.map((c, i) => (
                <details key={c.key} className="src-acc" open={!compact && i === 0}>
                  <summary className="src-acc-sum">
                    <div className="src-acc-copy">
                      <div className="src-card-std">{c.standard}</div>
                      {c.title && <div className="src-card-title">{c.title}</div>}
                      {c.docType && <span className="src-page-badge">{c.docType}</span>}
                    </div>
                    <ChevronDownIcon className="src-acc-chevron" size={14} />
                  </summary>
                  <div className="src-acc-body">
                    {c.heading && <div className="src-page-heading">{c.heading}</div>}
                    {c.sourceFile && <div className="src-page-file">{c.sourceFile}</div>}
                    {c.excerpt ? (
                      <SourceExcerpt text={c.excerpt} />
                    ) : (
                      <p className="src-page-excerpt src-page-empty">
                        No passage stored for this source.
                      </p>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/** @deprecated Use SourceStrip. Kept so older imports keep typechecking. */
export function Sources({ items }: { items: string[] | null | undefined }) {
  return <SourceStrip citations={items} />;
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

/** @deprecated Use SourceStrip. */
export function EvidenceSources({ items }: { items: EvidenceItem[] | null | undefined }) {
  return <SourceStrip sources={items} />;
}

/** Raw response JSON inspector — rendered only when developer mode is on. */
export function RawJson({ data, enabled }: { data: unknown; enabled: boolean }) {
  if (!enabled) return null;
  const [copied, setCopied] = useState(false);
  const timer = React.useRef<number | null>(null);
  React.useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  const handleCopy = async () => {
    try {
      const text = JSON.stringify(data, null, 2);
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      setCopied(true);
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <details className="rawjson">
      <summary>
        <span className="rawjson-summary-title">Inspect Raw API Response</span>
        <button
          type="button"
          className="pill-btn pill-btn-sm"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            handleCopy();
          }}
          aria-label="Copy raw JSON payload"
        >
          {copied ? (
            <>
              <CheckIcon size={12} />
              <span>Copied</span>
            </>
          ) : (
            <>
              <CopyIcon size={12} />
              <span>Copy JSON</span>
            </>
          )}
        </button>
      </summary>
      <div className="expand-wrap">
        <pre className="rawjson-code">{JSON.stringify(data, null, 2)}</pre>
      </div>
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
  onPick: (answer: string) => void | Promise<void>;
  onAssume: () => void | Promise<void>;
  onNewTopic: () => void | Promise<void>;
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
        <button type="button" className="pill-btn" disabled={disabled} onClick={onAssume}>
          Answer with assumptions
        </button>
        <span className="qacts-sep" aria-hidden="true">·</span>
        <button type="button" className="pill-btn" disabled={disabled} onClick={onNewTopic}>
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
  const done = value === 1 || value === -1;
  const [gone, setGone] = useState(false);
  useEffect(() => {
    if (!done) {
      setGone(false);
      return;
    }
    const t = window.setTimeout(() => setGone(true), 750);
    return () => window.clearTimeout(t);
  }, [done, value]);
  if (gone) return null;
  return (
    <div className={`fb${done ? " fb-done" : ""}`} role="group" aria-label="Rate this answer">
      <button
        type="button"
        className={`icon-btn fb-btn${value === 1 ? " active-pos fb-win" : done ? " fb-gone" : ""}`}
        aria-label="Helpful answer"
        aria-pressed={value === 1}
        disabled={disabled || done}
        onClick={() => onRate(1)}
        title="Helpful compliance guidance"
        tabIndex={done && value !== 1 ? -1 : undefined}
      >
        <ThumbsUpIcon size={16} />
      </button>
      <button
        type="button"
        className={`icon-btn fb-btn${value === -1 ? " active-neg fb-win" : done ? " fb-gone" : ""}`}
        aria-label="Unhelpful answer"
        aria-pressed={value === -1}
        disabled={disabled || done}
        onClick={() => onRate(-1)}
        title="Unhelpful or inaccurate guidance"
        tabIndex={done && value !== -1 ? -1 : undefined}
      >
        <ThumbsDownIcon size={16} />
      </button>
    </div>
  );
}

/** Shimmer placeholder while the model answer streams in. */
export function SkeletonAnswer() {
  return (
    <div className="assistant-message-row" role="status">
      <div className="assistant-avatar sk-avatar" aria-hidden="true">
        <span />
      </div>
      <div className="assistant-content sk-lines" aria-hidden="true">
        <span className="sk-line sk-w90" />
        <span className="sk-line sk-w70" />
        <span className="sk-line sk-w80" />
      </div>
      <span className="sr-only">Waiting for the assistant&apos;s response</span>
    </div>
  );
}
