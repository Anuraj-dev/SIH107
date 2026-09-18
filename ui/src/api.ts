import type { ChatResponse, Lang } from "./types";
import type { FeedbackResult, KbDiff, KbPublishResult, ThreadExport } from "./types";

export interface ServerThread {
  id: string;
  token: string;
}

/** Fixture KB diff used when the admin backend (GET /kb/diff) is not yet live (plan §5 stub). */
export const FIXTURE_KB_DIFF: KbDiff = {
  diff_id: "diff-fixture-001",
  generated_at: "2026-09-18T00:00:00+00:00",
  changes: [
    {
      id: "is-10500",
      is_number: "IS 10500:2012",
      change: "changed",
      old_status: "Active",
      new_status: "Active",
      source_url: "https://www.bis.gov.in/know-your-standard/",
      last_checked: "2026-09-18",
    },
    {
      id: "is-99999",
      is_number: "IS 99999:2026",
      change: "withdrawn",
      old_status: "Active",
      new_status: "Withdrawn",
      source_url: "https://www.bis.gov.in/know-your-standard/",
      last_checked: "2026-09-18",
    },
  ],
};

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

/**
 * Fixture-driven feedback: POST /feedback live when the backend ships it,
 * graceful fallback to fixture-ok when it 404s/is unreachable (plan §5).
 */
export async function sendFeedback(
  threadId: string,
  rating: 1 | -1,
  note?: string,
): Promise<FeedbackResult> {
  try {
    const j = await req("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        note ? { thread_id: threadId, rating, note } : { thread_id: threadId, rating },
      ),
    });
    if (j && j.ok === true) return { ok: true };
    return { ok: true, fixture: true };
  } catch {
    // Backend lacks POST /feedback (planned, not yet implemented) — record locally as fixture-ok.
    return { ok: true, fixture: true };
  }
}

/** GET /threads/{id} with owner token; throws so callers can fall back to the local transcript. */
export async function fetchThreadExport(thread: ServerThread): Promise<ThreadExport> {
  return (await req(`/api/threads/${encodeURIComponent(thread.id)}`, {
    headers: { "X-Owner-Token": thread.token },
  })) as ThreadExport;
}

/** Admin diff-review: live GET /kb/diff when available, else the bundled fixture (plan §5 stub). */
export async function fetchKbDiff(adminToken: string): Promise<{ diff: KbDiff; fixture: boolean }> {
  try {
    const j = (await req("/api/kb/diff", {
      headers: adminToken ? { "X-Owner-Token": adminToken } : {},
    })) as KbDiff;
    if (j && typeof j.diff_id === "string" && Array.isArray(j.changes)) {
      return { diff: j, fixture: false };
    }
    return { diff: FIXTURE_KB_DIFF, fixture: true };
  } catch {
    return { diff: FIXTURE_KB_DIFF, fixture: true };
  }
}

/** Admin publish decision: live POST /kb/publish when available, else fixture-ok. */
export async function publishKbDiff(
  diffId: string,
  decision: "approve" | "reject",
  adminToken: string,
): Promise<KbPublishResult> {
  try {
    const j = await req("/api/kb/publish", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(adminToken ? { "X-Owner-Token": adminToken } : {}),
      },
      body: JSON.stringify({ diff_id: diffId, decision }),
    });
    if (j && j.ok === true) return { ok: true, diff_id: diffId, decision };
    return { ok: true, diff_id: diffId, decision, fixture: true };
  } catch {
    return { ok: true, diff_id: diffId, decision, fixture: true };
  }
}
