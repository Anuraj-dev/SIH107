import type { ChatResponse, Lang } from "./types";

export interface ServerThread {
  id: string;
  token: string;
}

async function req(path: string, init?: RequestInit, timeoutMs = 15000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(path, { ...init, signal: ctl.signal });
    if (r.status === 410) throw new Error("Thread expired — starting a new topic");
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
  thread?: ServerThread | null,
  force = false,
): Promise<{ resp: ChatResponse; ms: number; thread: ServerThread | null }> {
  const t0 = performance.now();
  const body: Record<string, unknown> = { query, force };
  if (lang !== "auto") body.lang = lang;
  if (thread) body.thread_id = thread.id;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (thread) headers["X-Owner-Token"] = thread.token;
  const resp = (await req("/api/chat", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  })) as ChatResponse;
  const next: ServerThread | null = resp.thread_id
    ? { id: resp.thread_id, token: resp.owner_token ?? thread?.token ?? "" }
    : null;
  return { resp, ms: Math.round(performance.now() - t0), thread: next };
}
