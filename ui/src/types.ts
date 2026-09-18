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

export interface StructuredCitation {
  is_number: string;
  year: string;
  status: string;
  last_checked: string;
  source_url: string;
  display: string;
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
  /** Machine-readable citation rows (chat.py facade); absent on legacy responses. */
  structured_citations?: StructuredCitation[];
  thread_id?: string;
  owner_token?: string;
  /** RAG corpus evidence (title/standard number/link per chunk). */
  sources?: RagSource[];
  rag_evidence?: RagSource[];
  rag_mode?: string;
  rag_used_llm?: boolean;
  /** NLU intent for this turn (nlu.classify). */
  intent?: string;
  intent_confidence?: string;
  /** Extractive thread summary used for history-aware retrieval. */
  context_summary?: string;
  guidance_adaptive?: boolean;
}

export interface RagSource {
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

export interface FeedbackPayload {
  thread_id: string;
  rating: 1 | -1;
  note?: string;
}

export interface FeedbackResult {
  ok: boolean;
  /** true when the live backend lacks POST /feedback and the UI used the fixture fallback */
  fixture?: boolean;
  /** set when the call itself failed — show it instead of thanking */
  error?: string;
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

export type KbChangeKind = "added" | "changed" | "missing-upstream" | "withdrawn";

export interface KbChange {
  id: string;
  is_number: string;
  change: KbChangeKind;
  old_status?: string;
  new_status?: string;
  source_url?: string;
  last_checked?: string;
  /** live rows only: originating snapshot + raw details_json payload */
  snapshot_id?: number;
  details?: string;
}

export interface KbDiff {
  diff_id: string;
  generated_at: string;
  changes: KbChange[];
  /** live GET /kb/diff only: which admin key reviewed */
  reviewed_by?: string;
}

export interface KbPublishResult {
  ok: boolean;
  diff_id: string;
  decision: "approve" | "reject";
  fixture?: boolean;
  error?: string;
}

export interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
  resp?: ChatResponse;
  error?: string;
  ms?: number;
  system?: boolean;
  /** per-answer feedback state (fixture-driven until POST /feedback ships) */
  feedback?: 1 | -1 | null;
  feedbackNote?: string;
}
