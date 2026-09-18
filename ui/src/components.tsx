import React from "react";

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
            {isBullet && <span className="dot">•</span>}
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
