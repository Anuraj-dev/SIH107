export type Lang = "auto" | "en" | "hi";

export interface ThreadCtx {
  history: string[];
  rounds: number;
  force?: boolean;
}

export interface QuestionOpt {
  label: string;
  send: string;
}

export interface Question {
  slot: string;
  text: string;
  options: QuestionOpt[];
}

export interface ChatResponse {
  text: string;
  refused: boolean;
  kind: string;
  lang: "en" | "hi";
  citations: string[];
  pii: Record<string, boolean>;
  needs_info: boolean;
  questions: Question[];
  known: { slot: string; value: string }[];
  assumptions: string[];
  context: ThreadCtx;
  thread_id?: string;
  owner_token?: string;
}

export interface FeedbackPayload {
  thread_id: string;
  rating: 1 | -1;
  note?: string;
}

export interface FeedbackResult {
  ok: boolean;
  /** true when the live backend lacks POST /feedback and the UI used the fixture fallback */
  fixture?: boolean;
}

export interface ThreadMessage {
  role: string;
  text_redacted: string;
  citations_json: string;
  kind: string;
  ms: number;
  created_at: string;
}

export interface ThreadExport {
  thread_id: string;
  rounds: number;
  lang: string;
  messages: ThreadMessage[];
}

export type KbChangeKind = "added" | "changed" | "withdrawn";

export interface KbChange {
  id: string;
  is_number: string;
  change: KbChangeKind;
  old_status?: string;
  new_status: string;
  source_url: string;
  last_checked: string;
}

export interface KbDiff {
  diff_id: string;
  generated_at: string;
  changes: KbChange[];
}

export interface KbPublishResult {
  ok: boolean;
  diff_id: string;
  decision: "approve" | "reject";
  fixture?: boolean;
}

export interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
  resp?: ChatResponse;
  error?: string;
  ms?: number;
  /** per-answer feedback state (fixture-driven until POST /feedback ships) */
  feedback?: 1 | -1 | null;
  feedbackNote?: string;
}
