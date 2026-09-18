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
}

export interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
  resp?: ChatResponse;
  error?: string;
  ms?: number;
}
