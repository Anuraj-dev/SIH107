import React, { useState } from "react";

/** Tiny **bold** + bullet renderer — no deps, avoids HTML injection. */
export function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((ln, i) => {
        const trimmed = ln.trim();
        const isBullet = trimmed.startsWith("- ");
        const body = isBullet ? trimmed.slice(2) : ln;
        const parts = body.split("**");
        return (
          <div key={i} className={isBullet ? "line bullet" : "line"}>
            {isBullet && <span className="dot" aria-hidden="true">•</span>}
            <span>
              {parts.map((p, j) =>
                j % 2 === 1 ? <strong key={j}>{p}</strong> : <React.Fragment key={j}>{p}</React.Fragment>,
              )}
            </span>
          </div>
        );
      })}
    </>
  );
}

export function Badge({ children, tone }: { children: React.ReactNode; tone: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

/** Server-provided `known[]` rendered as "known so far" chips (plan §5). */
export function KnownChips({ known }: { known: { slot: string; value: string }[] }) {
  if (!known || known.length === 0) return null;
  return (
    <div className="known" aria-label="Known so far">
      <span className="known-h" id="known-h">Known so far:</span>
      <ul className="known-list" aria-labelledby="known-h">
        {known.map((k) => (
          <li key={k.slot} className="known-chip">{k.slot} = {k.value}</li>
        ))}
      </ul>
    </div>
  );
}

/** Server-provided `assumptions[]` rendered as a warning banner (plan §5). */
export function AssumptionsBanner({ items }: { items: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="assume" role="note" aria-label="Answer uses assumptions">
      <strong>Answering with assumptions</strong> — you didn&rsquo;t specify these, still confirm with BIS:
      <ul>
        {items.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
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
        aria-label="Thumbs up — helpful answer"
        aria-pressed={value === 1}
        disabled={disabled}
        onClick={() => onRate(1)}
      >
        👍<span className="sr-only"> helpful</span>
      </button>
      <button
        type="button"
        className={`fb-btn${value === -1 ? " active" : ""}`}
        aria-label="Thumbs down — unhelpful answer"
        aria-pressed={value === -1}
        disabled={disabled}
        onClick={() => onRate(-1)}
      >
        👎<span className="sr-only"> unhelpful</span>
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
        placeholder="Optional note (no personal details)…"
        maxLength={500}
      />
      <button type="submit" className="ghost" disabled={!note.trim()}>send note</button>
    </form>
  );
}
