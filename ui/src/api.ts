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
  newTopic = false,
): Promise<{ resp: ChatResponse; ms: number; thread: ServerThread | null }> {
  const t0 = performance.now();
  const body: Record<string, unknown> = { query, force, new_topic: newTopic };
  if (lang !== "auto") body.lang = lang;
  // Design 3: new_topic ignores thread server-side; don't send a stale id.
  if (thread && !newTopic) body.thread_id = thread.id;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (thread && !newTopic) headers["X-Owner-Token"] = thread.token;
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
 * Design 3 common-case facade: one happy-path entry point with strong defaults.
 * `sendChat` above stays as the low-level compat primitive; new code should
 * prefer `bisChat.send()` which centralises the fresh/force policy.
 */
export interface BisChatSendOpts {
  lang?: Lang;
  thread?: ServerThread | null;
  force?: boolean;
  /** Drop follow-up context server-side (POSTs new_topic, sends no stale id). */
  fresh?: boolean;
}

export const bisChat = {
  async send(
    query: string,
    opts: BisChatSendOpts = {},
  ): Promise<{ resp: ChatResponse; ms: number; thread: ServerThread | null }> {
    const { lang = "auto", thread = null, force = false, fresh = false } = opts;
    return sendChat(query, lang, fresh ? null : thread, force, fresh);
  },
  /** Design 3 policy (mirrors App + chat.py): keep the thread while clarifying. */
  shouldKeepThread(resp: ChatResponse): boolean {
    return resp.needs_info === true;
  },
  newTopic(): null {
    return null;
  },
};

/** Stateful closure for non-React callers; React (App.tsx) keeps thread in state. */
export function createBisChat(initialLang: Lang = "auto") {
  let thread: ServerThread | null = null;
  let lang: Lang = initialLang;
  return {
    getThread: (): ServerThread | null => thread,
    setLang: (l: Lang): void => {
      lang = l;
    },
    newTopic(): void {
      thread = null;
    },
    async send(
      query: string,
      opts: { force?: boolean; fresh?: boolean; lang?: Lang } = {},
    ): Promise<{ resp: ChatResponse; ms: number; thread: ServerThread | null }> {
      const out = await bisChat.send(query, {
        lang: opts.lang ?? lang,
        thread: opts.fresh ? null : thread,
        force: opts.force ?? false,
        fresh: opts.fresh ?? false,
      });
      thread = bisChat.shouldKeepThread(out.resp) ? out.thread : null;
      return out;
    },
  };
}
/**
 * Fixture-driven feedback: live POST /feedback when the backend ships it
 * (body {thread_id, rating: 1|-1, note}, X-Owner-Token for owned threads),
 * graceful fallback to fixture-ok otherwise (plan §5).
 */
export async function sendFeedback(
  threadId: string,
  rating: 1 | -1,
  ownerToken?: string,
  note?: string,
): Promise<FeedbackResult> {
  try {
    const j = await req("/api/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(ownerToken ? { "X-Owner-Token": ownerToken } : {}),
      },
      // Backend schema: {thread_id, rating: -1..1, note: str ≤1000}; UI only ever sends ±1.
      body: JSON.stringify({ thread_id: threadId, rating, note: note ?? "" }),
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

/** Live pending_diffs row shape from GET /kb/diff (Phase 4 backend). */
interface LiveDiffRow {
  id: number;
  snapshot_id: number;
  change_type: string;
  is_number: string;
  details_json: string;
  status: string;
  decided_at: string | null;
}

function normaliseLiveDiff(j: { pending: LiveDiffRow[]; reviewed_by?: string }): KbDiff {
  return {
    diff_id: "live",
    generated_at: new Date().toISOString(),
    reviewed_by: j.reviewed_by,
    changes: j.pending.map((r) => ({
      id: String(r.id),
      is_number: r.is_number,
      change: (["added", "changed", "missing-upstream"].includes(r.change_type)
        ? r.change_type
        : "changed") as KbDiff["changes"][number]["change"],
      snapshot_id: r.snapshot_id,
      details: r.details_json,
    })),
  };
}

/** Admin diff-review: live GET /kb/diff (x-admin-key) when available, else the bundled fixture. */
export async function fetchKbDiff(adminKey: string): Promise<{ diff: KbDiff; fixture: boolean }> {
  try {
    const j = (await req("/api/kb/diff", {
      headers: adminKey ? { "x-admin-key": adminKey } : {},
    })) as KbDiff & { pending?: LiveDiffRow[]; reviewed_by?: string };
    if (Array.isArray(j.pending)) {
      return { diff: normaliseLiveDiff(j as { pending: LiveDiffRow[]; reviewed_by?: string }), fixture: false };
    }
    if (j && typeof j.diff_id === "string" && Array.isArray(j.changes)) {
      return { diff: j, fixture: false };
    }
    return { diff: FIXTURE_KB_DIFF, fixture: true };
  } catch {
    return { diff: FIXTURE_KB_DIFF, fixture: true };
  }
}

/**
 * Admin publish decision: live POST /kb/publish
 * ({diff_id: int, approve: bool, publisher_key, approver_key} — 2-person, distinct actors)
 * when available, else fixture-ok.
 */
export async function publishKbDiff(
  diffId: string,
  decision: "approve" | "reject",
  publisherKey: string,
  approverKey?: string,
): Promise<KbPublishResult> {
  const pub = publisherKey.trim();
  const appr = (approverKey ?? "").trim();
  if (pub && appr && pub !== appr && /^\d+$/.test(diffId)) {
    try {
      const j = await req("/api/kb/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          diff_id: Number(diffId),
          approve: decision === "approve",
          publisher_key: pub,
          approver_key: appr,
        }),
      });
      if (j && j.ok === true) return { ok: true, diff_id: diffId, decision };
    } catch {
      // fall through to fixture-ok
    }
  }
  // Fixture endpoint: single-key review or non-numeric fixture diff id.
  try {
    await req("/api/kb/publish", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(pub ? { "X-Owner-Token": pub } : {}),
      },
      body: JSON.stringify({ diff_id: diffId, decision }),
    });
  } catch {
    // fixture-ok without a live backend
  }
  return { ok: true, diff_id: diffId, decision, fixture: true };
}
