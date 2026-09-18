import type { ChatResponse, Lang, ThreadCtx } from "./types";

async function req(path: string, init?: RequestInit, timeoutMs = 15000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(path, { ...init, signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const j = await req("/api/health");
    return j?.ok === true;
  } catch {
    return false;
  }
}

export async function sendChat(
  query: string,
  lang: Lang,
  context?: ThreadCtx | null,
  force = false,
): Promise<{ resp: ChatResponse; ms: number }> {
  const t0 = performance.now();
  const body: Record<string, unknown> = { query };
  if (lang !== "auto") body.lang = lang;
  if (context && (context.history.length > 0 || context.rounds > 0))
    body.context = { ...context, force };
  else if (force) body.context = { history: [query], rounds: 0, force: true };
  const resp = (await req("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })) as ChatResponse;
  return { resp, ms: Math.round(performance.now() - t0) };
}
