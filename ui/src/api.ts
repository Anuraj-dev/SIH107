import type { ChatResponse, Lang } from "./types";
import type { FeedbackResult, KbDiff, KbPublishResult, ThreadExport } from "./types";

export interface ServerThread {
  id: string;
  token: string;
}

const CHAT_TIMEOUT_MS = 120_000;

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
  const raw = (await req("/api/chat", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  }, CHAT_TIMEOUT_MS)) as Partial<ChatResponse>;
  const resp = normalizeChatResponse(raw, query);
  const next: ServerThread | null = resp.thread_id
    ? { id: resp.thread_id, token: resp.owner_token ?? thread?.token ?? "" }
    : null;
  return { resp, ms: Math.round(performance.now() - t0), thread: next };
}

/**
 * Validate/normalize any /chat payload into a full ChatResponse (issue #4
 * P1-13): proxy errors, version drift, or truncated bodies must degrade to
 * an inline error answer instead of crashing on `resp!.field` access.
 */
export function normalizeChatResponse(raw: unknown, query = ""): ChatResponse {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const str = (v: unknown, fb = ""): string => (typeof v === "string" ? v : fb);
  const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
  const lang = r.lang === "hi" ? "hi" : "en";
  if (typeof r.text !== "string" || typeof r.refused !== "boolean") {
    return {
      text: "The chatbot is unavailable because the server returned an invalid response. Please try again later.",
      refused: false,
      kind: "model_unavailable",
      lang,
      citations: [],
      pii: {},
      needs_info: false,
      questions: [],
      known: [],
      assumptions: [],
      context: { history: query ? [query] : [], rounds: 0 },
      rag_used_llm: false,
      model_available: false,
    };
  }
  return {
    text: str(r.text),
    refused: r.refused as boolean,
    kind: str(r.kind, "answered"),
    lang,
    citations: arr<string>(r.citations).filter((c) => typeof c === "string"),
    pii: (r.pii && typeof r.pii === "object" ? r.pii : {}) as Record<string, boolean>,
    needs_info: r.needs_info === true,
    questions: arr(r.questions),
    known: arr(r.known),
    assumptions: arr<string>(r.assumptions).filter((a) => typeof a === "string"),
    context: (r.context && typeof r.context === "object"
      ? r.context
      : { history: [], rounds: 0 }) as ChatResponse["context"],
    structured_citations: arr(r.structured_citations),
    thread_id: typeof r.thread_id === "string" ? r.thread_id : undefined,
    owner_token: typeof r.owner_token === "string" ? r.owner_token : undefined,
    sources: arr(r.sources ?? r.rag_evidence),
    rag_evidence: arr(r.rag_evidence ?? r.sources),
    rag_mode: typeof r.rag_mode === "string" ? r.rag_mode : undefined,
    rag_used_llm: r.rag_used_llm === true,
    model_available: r.model_available === true,
    intent: typeof r.intent === "string" ? r.intent : undefined,
    intent_confidence: typeof r.intent_confidence === "string" ? r.intent_confidence : undefined,
    context_summary: typeof r.context_summary === "string" ? r.context_summary : undefined,
    guidance_adaptive: r.guidance_adaptive === true,
  };
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
  /** Keep context across every model turn, not only clarification turns. */
  shouldKeepThread(resp: ChatResponse): boolean {
    return true;
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
 * POST /feedback when the backend ships it
 * (body {thread_id, rating: -1..1, note}, X-Owner-Token for owned threads).
 * Honest states (issue #4 P1-14): `{ok:true}` live, `{ok:true, fixture:true}`
 * when the backend has no feedback route yet, `{ok:false, error}` when the
 * call itself failed — callers must surface that instead of thanking.
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
    return { ok: false, error: "feedback was not accepted" };
  } catch (e) {
    const msg = e instanceof Error ? e.message : "request failed";
    if (/HTTP 404/.test(msg)) return { ok: true, fixture: true };
    return { ok: false, error: msg };
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

/** Admin diff-review: live GET /kb/diff (x-admin-key). 403/network is failure, never a fixture unlock. */
export async function fetchKbDiff(adminKey: string): Promise<{ diff: KbDiff; fixture: boolean }> {
  const j = (await req("/api/kb/diff", {
    headers: adminKey ? { "x-admin-key": adminKey } : {},
  })) as KbDiff & { pending?: LiveDiffRow[]; reviewed_by?: string };
  if (Array.isArray(j.pending)) {
    return { diff: normaliseLiveDiff(j as { pending: LiveDiffRow[]; reviewed_by?: string }), fixture: false };
  }
  throw new Error("KB diff is not a live pending payload");
}

/**
 * Publish decision: live POST /kb/publish
 * ({diff_id: int, approve: bool, publisher_key, approver_key} — 2-person, distinct actors)
 * only when the row id is numeric (a real pending_diffs id) and both keys are
 * present; otherwise record locally as fixture-ok WITHOUT posting a shape
 * the backend would 422 (issue #4 P1-14).
 */
export async function publishKbDiff(
  changeId: string,
  decision: "approve" | "reject",
  publisherKey: string,
  approverKey?: string,
): Promise<KbPublishResult> {
  const pub = publisherKey.trim();
  const appr = (approverKey ?? "").trim();
  if (pub && appr && pub !== appr && /^\d+$/.test(changeId)) {
    try {
      const j = await req("/api/kb/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          diff_id: Number(changeId),
          approve: decision === "approve",
          publisher_key: pub,
          approver_key: appr,
        }),
      });
      if (j && j.ok === true) return { ok: true, diff_id: changeId, decision };
      return { ok: false, diff_id: changeId, decision, error: "backend rejected the publish" };
    } catch (e) {
      return { ok: false, diff_id: changeId, decision, error: e instanceof Error ? e.message : "request failed" };
    }
  }
  return { ok: true, diff_id: changeId, decision, fixture: true };
}
