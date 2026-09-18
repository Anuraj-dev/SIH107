/**
 * UI-MS contract test (plan §9): validates ui/tests/fixtures/*.json against the
 * shapes ui/src consumes (types.ts + api.ts). Recorded fixtures, no live backend.
 *
 * Run: npm run test:contract
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "fixtures");
const files = readdirSync(root).filter((f) => f.endsWith(".json"));
const load = (f) => JSON.parse(readFileSync(join(root, f), "utf8"));

function assertChatResponse(resp, label) {
  assert.equal(typeof resp.text, "string", `${label}: text must be string`);
  assert.equal(typeof resp.refused, "boolean", `${label}: refused must be boolean`);
  assert.equal(typeof resp.kind, "string", `${label}: kind must be string`);
  assert.ok(["en", "hi"].includes(resp.lang), `${label}: lang must be en|hi, got ${resp.lang}`);
  assert.ok(Array.isArray(resp.citations), `${label}: citations must be array`);
  for (const c of resp.citations) assert.equal(typeof c, "string", `${label}: citation must be string`);
  assert.equal(typeof resp.pii, "object", `${label}: pii must be object`);
  assert.equal(typeof resp.needs_info, "boolean", `${label}: needs_info must be boolean`);
  assert.ok(Array.isArray(resp.questions), `${label}: questions must be array`);
  for (const q of resp.questions) {
    assert.equal(typeof q.slot, "string", `${label}: question.slot must be string`);
    assert.equal(typeof q.text, "string", `${label}: question.text must be string`);
    assert.ok(Array.isArray(q.options), `${label}: question.options must be array`);
    for (const o of q.options) {
      assert.equal(typeof o.label, "string", `${label}: option.label must be string`);
      assert.equal(typeof o.send, "string", `${label}: option.send must be string`);
    }
  }
  assert.ok(Array.isArray(resp.known), `${label}: known must be array`);
  for (const k of resp.known) {
    assert.equal(typeof k.slot, "string", `${label}: known.slot must be string`);
    assert.equal(typeof k.value, "string", `${label}: known.value must be string`);
  }
  assert.ok(Array.isArray(resp.assumptions), `${label}: assumptions must be array`);
  for (const a of resp.assumptions) assert.equal(typeof a, "string", `${label}: assumption must be string`);
  // Thread continuation fields the UI relies on (server.py mints thread_id + owner_token).
  if (resp.thread_id !== undefined) assert.equal(typeof resp.thread_id, "string", `${label}: thread_id must be string`);
  if (resp.owner_token !== undefined) assert.equal(typeof resp.owner_token, "string", `${label}: owner_token must be string`);
  // needs_info invariant: must carry at least one question so the UI has something to render.
  if (resp.needs_info) {
    assert.ok(resp.questions.length > 0, `${label}: needs_info=true requires ≥1 question`);
  }
  // Refusal invariant: refusals carry no known/assumptions (nothing grounded to show).
  if (resp.refused) {
    assert.equal(resp.known.length, 0, `${label}: refused answers must not carry known[]`);
    assert.equal(resp.assumptions.length, 0, `${label}: refused answers must not carry assumptions[]`);
  }
}

describe("ui contract fixtures", () => {
  it("fixture set is complete", () => {
    for (const expected of [
      "chat-answered.json",
      "chat-needs-info.json",
      "chat-hindi.json",
      "chat-hinglish.json",
      "chat-refused.json",
      "feedback.json",
      "thread-export.json",
      "kb-diff.json",
    ]) {
      assert.ok(files.includes(expected), `missing fixture ${expected}`);
    }
  });

  it("chat fixtures match the ChatResponse shape ui/src consumes", () => {
    for (const f of files.filter((x) => x.startsWith("chat-"))) {
      const j = load(f);
      assertChatResponse(j.response, f);
    }
  });

  it("needs_info flow fixture carries questions + thread continuation", () => {
    const j = load("chat-needs-info.json");
    assert.equal(j.response.needs_info, true);
    assert.ok(j.response.questions.length >= 1 && j.response.questions.length <= 2);
    assert.ok(j.response.thread_id, "needs_info must carry thread_id for follow-ups");
  });

  it("hindi fixtures use lang=hi (lang badge shows हिंदी)", () => {
    for (const f of ["chat-hindi.json", "chat-hinglish.json"]) {
      const j = load(f);
      assert.equal(j.response.lang, "hi", `${f}: lang badge contract requires lang=hi`);
    }
    const dev = load("chat-hindi.json").response.text;
    assert.match(dev, /[\u0900-\u097F]/, "chat-hindi fixture must contain Devanagari");
  });

  it("RAG/intent fields are validated when present (issue #4 P1-12)", () => {
    for (const f of files.filter((x) => x.startsWith("chat-"))) {
      const resp = load(f).response;
      if (resp.sources !== undefined) {
        assert.ok(Array.isArray(resp.sources), `${f}: sources must be array`);
        for (const s of resp.sources) {
          for (const k of ["standard_number", "title", "url", "doc_type"]) {
            assert.equal(typeof s[k], "string", `${f}: source.${k} must be string`);
          }
          assert.equal(typeof s.score, "number", `${f}: source.score must be number`);
        }
      }
      if (resp.rag_mode !== undefined) assert.equal(typeof resp.rag_mode, "string");
      if (resp.rag_used_llm !== undefined) assert.equal(typeof resp.rag_used_llm, "boolean");
      if (resp.intent !== undefined) assert.equal(typeof resp.intent, "string");
      if (resp.intent_confidence !== undefined) {
        assert.ok(["high", "medium", "low"].includes(resp.intent_confidence));
      }
      if (resp.guidance_adaptive !== undefined) assert.equal(typeof resp.guidance_adaptive, "boolean");
    }
    const c = load("chat-corpus.json").response;
    assert.equal(c.kind, "corpus_answer");
    assert.equal(c.rag_used_llm, true);
    assert.ok(c.sources.length > 0 && c.sources[0].standard_number.includes("IS 101"));
  });

  it("feedback fixture matches POST /feedback contract", () => {
    const j = load("feedback.json");
    assert.equal(j.response.ok, true);
    assert.equal(j.response.status, "pending");
    assert.deepEqual(j.contract.rating_enum, [1, -1]);
    assert.equal(j.contract.note_max_length, 1000);
    for (const ex of j.request_examples) {
      assert.equal(typeof ex.thread_id, "string");
      assert.ok([1, -1].includes(ex.rating), "rating must be 1|-1");
      if (ex.note !== undefined) assert.ok(ex.note.length <= j.contract.note_max_length);
    }
  });

  it("thread-export fixture matches GET /threads/{id} redacted shape", () => {
    const r = load("thread-export.json").response;
    assert.equal(typeof r.thread_id, "string");
    assert.equal(typeof r.rounds, "number");
    assert.equal(typeof r.lang, "string");
    assert.ok(Array.isArray(r.messages) && r.messages.length > 0);
    for (const m of r.messages) {
      for (const k of ["role", "text_redacted", "citations_json", "kind", "ms", "created_at"]) {
        assert.ok(k in m, `thread message missing ${k}`);
      }
      assert.ok(!("text" in m), "export must use redacted text_redacted, never raw text");
      assert.ok(!("owner_token_hash" in m), "export must not leak token hashes");
    }
  });

  it("kb-diff fixture matches the admin diff/publish shapes", () => {
    const j = load("kb-diff.json");
    // Live backend shapes the UI normalises (documented in-fixture, asserted here).
    assert.deepEqual(j.live_shapes.get_diff.change_type_enum, ["added", "changed", "missing-upstream"]);
    assert.equal(j.live_shapes.get_diff.auth_header, "x-admin-key");
    const pub = j.live_shapes.publish.body_example;
    assert.equal(typeof pub.diff_id, "number");
    assert.equal(typeof pub.approve, "boolean");
    assert.ok(pub.publisher_key && pub.approver_key, "2-person publish needs both keys");
    // Normalised/fixture diff shape the UI table consumes.
    const d = j.diff;
    assert.equal(typeof d.diff_id, "string");
    assert.equal(typeof d.generated_at, "string");
    assert.ok(Array.isArray(d.changes) && d.changes.length > 0);
    for (const c of d.changes) {
      assert.equal(typeof c.id, "string");
      assert.equal(typeof c.is_number, "string");
      // Superset: live change_type values plus "withdrawn", which the UI renders as a warning row.
      assert.ok(["added", "changed", "missing-upstream", "withdrawn"].includes(c.change), `bad change kind ${c.change}`);
    }
    assert.ok(["approve", "reject"].includes(j.publish_request_example.decision));
    assert.equal(j.publish_response.ok, true);
    assert.equal(j.publish_response.diff_id, d.diff_id);
  });
});
