# BIS Conversational Assistant — Production Implementation Plan
_Date: 2026-09-18 | Method: ECC blueprint (research → design → draft → review → register)_
_Source docs: `docs/product-brief.md`, `docs/decisions.md` (decisions #1–#11)_
_Status: APPROVED + IMPLEMENTED (Phases 0–9, 2026-09-18; go-no-go conditional GO, human sign-off pending §10.7)_

> Current state: working MVP (stdlib Python API + React/TS Vite UI, 16 curated
> standards rows — 15 real + 1 withdrawn demo — + 4 schemes + 5 lab samples +
> 6 glossary terms in curated JSON, slot-driven multi-turn grounding, 17 unit
> tests, 52-item gold eval at 100%). Breadth tier (this fix): ~22,471
> list-level metadata rows via `scripts/breadth_crawl.py` into SQLite
> (`docs/data-sources-research.md`); curated rows stay authoritative.
> This plan takes the MVP to a production-oriented pilot without violating any grilled decision.

## 0. Non-negotiable invariants (verify after EVERY phase)

1. Allowlisted BIS sources only — no third-party full-text scraping (decision #2, #3).
2. Strict citations on every factual claim; refuse when source missing (decision #4).
3. No single definitive IS; multi-turn grounding holds (decisions #5, #11).
4. Never-infer list enforced + tested (decision #10).
5. EN+HI end-to-end; DPDP consent/minimisation/deletion for business PII (decisions #6, #8).
6. Eval gate ≥90% stays green; no phase merges on red.

---

## 1. Target architecture

```
                    ┌──────────────┐
                    │  React + TS  │  ui/ (Vite) — chat console, admin KB view,
                    │  Vite UI     │  feedback buttons, EN/HI, a11y
                    └──────┬───────┘
                           │ HTTPS /api (CORS allowlist, rate-limit, API keys)
              ┌────────────▼────────────┐
              │  API service (Python)   │  src/bis_assistant/api.py → FastAPI/uvicorn
              │  threads │ safety │ PII  │  server-side thread store, request IDs,
              │  auth │ rate-limit        │  redacted structured logs
              └───┬──────────┬──────────┘
                  │          │
     ┌────────────▼───┐  ┌───▼──────────────────┐
     │ Versioned KB   │  │ Retrieval + citation │
     │ (SQLite→PG)    │  │ BM25/hybrid, slots,  │
     │ snapshots+diff │  │ citation verifier    │
     └────────┬───────┘  └──────────────────────┘
              │
   ┌──────────▼──────────┐    ┌──────────────────┐
   │ Ingestion workers   │    │ Observability    │
   │ allowlist crawler,  │───▶│ metrics/logs/    │
   │ refresh scheduler   │    │ traces, alerts   │
   └─────────────────────┘    └──────────────────┘
```

Production deltas from MVP: stdlib `http.server` → FastAPI+uvicorn; flat JSON →
versioned relational KB; in-memory consent → durable consent ledger + purge job;
client-held thread context → server-side threads; ad-hoc logs → structured logs +
metrics; single gold file → versioned eval datasets in CI.

## 2. Data model

**KB tables** (every row carries `source_url`, `captured_at`, `last_checked`, `status`):
- `standards(id, is_number, year, title_en, title_hi, scope_en, scope_hi, status,
  scheme_key, source_url, esale_url, section_ref, source_snippet, qco_status,
  qco_checked_at, captured_at, last_checked, supersedes, version)`
  - `section_ref`/`source_snippet`: the exact section shown on the source page (may be
    empty → verifier then forbids clause numbers and forces link-out).
  - `qco_status` ∈ {unknown, not-covered, compulsory, exempt}, always human-reviewed.
- `standard_versions` (append-only snapshots per refresh; diff view for review)
- `schemes(key, name_en/hi, steps_en/hi, apply_url, source_url, last_checked)`
- `labs(id, name, city, type, scope_note, source_url, last_checked)` — sample rows stay
  flagged `unverified` until confirmed on LIMS
- `glossary(term, en, hi, source_url)`
- `slots(is_number, key, q_en, q_hi, options_json, pattern)` — migrates `slots.py` to data
- `info_pages(key, title, url, last_checked)` — curated links with no IS mapping:
  training calendar, Standards Clubs, consumer-complaint registration. Seeds from the
  currently hardcoded assistant URLs; reviewed like any KB row.

**Operational tables:**
- `threads(id, user_ref, history_redacted_json, rounds, lang, created_at, updated_at, expires_at, owner_token_hash)`
  — thread history is redacted-at-write via `redact()`; never raw query text.
- `messages(id, thread_id, role, text_redacted, citations_json, kind, ms, created_at)`
- `consents(user_ref, purpose, granted_at, expires_at, revoked_at)` — DPDP receipts
- `profiles(user_ref, fields_json, updated_at)` — minimised business fields only
- `feedback(message_id, rating, note_redacted, status, created_at)` — `status` ∈
  {pending, approved, spam} via moderation queue
- `kb_reviews(diff_id, publisher, approver, decided_at)` — publish requires two
  DISTINCT actors, enforced by DB check constraint
- `audit_log(actor, action, target_ref, at)` — post-erasure only tombstones
  `{actor, action, at}`, no payload
- `eval_runs(id, dataset_version, scores_json, at, gate_pass)`

Erasure scope (`DELETE /me`, ≤24 h): profile + threads + messages + feedback rows
deleted; audit keeps tombstone only. Retention: threads/messages 90 days then purge;
test-report uploads never persisted (session-only).

Thread ownership: anonymous threads are scoped to a per-thread owner token issued at
`POST /threads`; every mutating call must present it. Cross-user delete/export denial
is contract-tested.

## 3. Source ingestion & versioning

- **Allowlist crawler** (`ingest/`): seed list = Know-Your-Standard portal, BIS scheme/
  hallmarking/lab/training pages, CRS portal, LIMS search, e-sale catalogue. Enforce
  host allowlist in code (already in `retriever.py`) + robots/ToS respect + crawl-delay.
- **Snapshot + diff**: each run stores raw snapshots; differ produces
  added/changed/withdrawn records → human review queue before publish. Withdrawn or
  superseded IS flips `status` and triggers citation warnings automatically.
- **Supersession map**: `supersedes` chain (e.g. IS 10500:2012 → rev) surfaced in answers;
  QCO/compulsion flags tracked per IS with `qco_status`, `qco_checked_at`.
- **Refresh cadence**: weekly auto-crawl + on-demand re-check when BIS notifications land;
  every published answer stamps the row's `last_checked`.
- **No-go preserved**: crawler refuses non-allowlisted hosts and full-text PDF
  mirroring; full text stays behind e-sale links (decisions #2, #3).

## 4. Retrieval & citation design

- **Stage 1 — lexical**: BM25 (or current keyword scorer as baseline) over
  `is_number/year/title/scope/keywords`, plus Hinglish/Devanagari normalisation and
  singularisation (keep current `_tokens` behaviour as regression baseline).
- **Stage 2 — slot grounding**: per-IS slots (§slots table); vague query → ask ≤2 most
  discriminative questions/turn; answer only on exact IS / score≥15+margin≥5 /
  all-slots-filled / force / 2 rounds exhausted (decision #11 thresholds, tunable via config).
- **Stage 3 — citation verifier** (new): every factual sentence must map to ≥1 KB row
  (+ its `section_ref` where the claim needs clause depth; empty `section_ref` →
  link-out + refuse clause text). IS numbers regex-extracted from output must exactly
  match cited rows; mismatch → refuse.
- **Journeys**: hallmark/lab/scheme/club/glossary intents bypass interrogation (current
  behaviour, keep + test).
- **Config, not code**: thresholds (`DIRECT_SCORE`, `MARGIN`, `FLOOR`, `MAX_ROUNDS`)
  move to `config.yaml` with eval-gated tuning protocol (any change must re-run §8 gate).

## 5. API / UI

- **API**: `POST /chat {query, lang?, thread_id?}` (server-authoritative threads;
  legacy client-held `context` rejected after Phase-3 cutover; unknown/expired id → `410`),
  `GET /health`, `POST /threads` (returns `{thread_id, owner_token, expires_at}`),
  `DELETE /threads/{id}` (owner token), `POST /consent`, `DELETE /me` (DPDP erasure),
  `GET /me/export` (self PII export), `POST /feedback`,
  admin `GET /kb/diff` + `POST /kb/publish` (auth-gated, 2-person).
  Errors: machine-readable `{error, code, retryable}`; every response carries `request_id`.
  Rate limits: anonymous 30 req/h/IP + `/chat` burst 5/min; registered 300 req/h —
  validated in Phase-8 load test.
- **UI**: keep test console; add feedback thumbs per answer, "known so far" chips,
  assumption banners, conversation export (redacted), admin diff-review screen,
  Hindi/Hinglish keyboard-friendly input, WCAG-AA contrast/focus/keyboard pass.
- **Clients**: CLI keeps parity for demos; static `web/` page removed in Phase 5
  (React already shipped; redirect note in README).

## 6. Access control

| Actor | Public chat | Feedback | Thread delete | KB diff review | KB publish | PII export |
|---|---|---|---|---|---|---|
| Anonymous user | ✓ (rate-limited) | ✓ | own threads | — | — | — |
| Registered MSME user | ✓ (higher limits) | ✓ | ✓ (`DELETE /me`) | — | — | own |
| BIS reviewer/admin | ✓ | ✓ | — | ✓ | ✓ (2-person) | — (audit-logged) |

- Admin behind SSO (provider chosen in Phase 4) or scoped API keys with rotation SOP;
  publish requires 2-person approval via `kb_reviews` (distinct actors enforced).
- Registered MSME accounts: OTP-based registration (flow defined in Phase 4); anonymous
  feedback enters the moderation queue, never auto-publishes.
- PII export only self-service (`GET /me/export`); admin sees redacted text only.
- Rate limits: anonymous 30 req/h/IP, registered 300 req/h; burst caps on `/chat`.

## 7. Observability

- **Logs**: JSON structured, `request_id` everywhere. Store `text_redacted` ONLY —
  raw query text never reaches logs, DB, or traces. Redaction = `redact()` blocklist
  PLUS field-level rule (no raw-text columns exist); CI log-grep uses seeded PII
  fixtures (phone/email/Aadhaar/name/address/firm), not regex self-check.
- **Metrics** (Prometheus-style; SLO in Phase 8, owner on-call):
  `chat_latency_ms` (p95 <2 s, 5-min window), `refusal_rate{kind}` (swing >10 pts/1 h),
  `needs_info_rate`, `clarify_rounds_hist`, `citation_fail_total` (any trip pages),
  `kb_staleness_days` (>14 pages), `eval_gate_pass`, `feedback_neg_rate` (>15%/day).
- **Alerts**: verifier trips spike, refusal-rate swing >10 pts, KB older than 14 days,
  p95 latency >2 s, 5xx on `/chat`.
- **Traces**: sample 5% of `/chat` (redacted BEFORE sampling) end-to-end
  retriever→slots→verifier; trace retention 14 days.

## 8. Evaluation datasets (versioned under `eval/datasets/vN/`)

- `gold-product.json` (≥100): product→IS incl. Hindi/Hinglish, ambiguous pairs
  (10500 vs 14543), withdrawn traps.
- `gold-schemes.json` (≥30): ISI/CRS/FMCS/hallmarking/lab journeys + Standards-Club/
  training/complaint items (served from `info_pages`).
- `gold-glossary.json` (≥20): plain EN/HI term explanations, graded for no normative
  drift; wired into the ship gate (brief §10).
- `adversarial-never-infer.json` (≥40): cert claims, full-text demands, clause quotes,
  licence guarantees, lab-result predictions, legal-advice framings, jailbreak paraphrases.
- `multilingual.json` (≥40): EN/HI/Hinglish parallels with same expected IS.
- `versioning.json` (≥15): superseded/withdrawn handling, `last-checked` presence.
- Authoring: sourced from BIS pages listed in KB rows, second-reviewer sign-off per file;
  per-dimension metrics defined as groundedness (claim→row support), citation-precision
  (cited rows actually support the sentence), refusal-F1, scheme accuracy, HI parity delta.
- Harness reports per-dimension pass rates + refusal calibration; dataset versions pinned
  in CI; human spot-review queue for low-confidence answers feeds back as new items.

## 9. Test strategy

- **Unit** (keep `tests/`, expand): scorer, slots, safety patterns, privacy, citations.
- **Contract**: API schema tests; UI-MS W contract via recorded fixtures (no live backend).
- **Snapshot**: golden-answer snapshots for top-20 queries; diff reviewed, never auto-updated.
- **Integration**: API→KB→retriever→verifier with seeded SQLite; crawler against fixtures.
- **Journey E2E** (brief §3 primary task): 5 canonical MSME journeys
  (product→IS→scheme→LIMS-scope→disclaimer, EN+HI) against seeded SQLite — the
  end-to-end chain must pass even when secondary journeys are degraded.
- **Load**: k6/Locust on `/chat` (reference env: single uvicorn worker, 2 vCPU/4 GB;
  target p95 <2 s @ 50 rps).
- **KB-staleness drill**: inject withdrawn IS, assert warnings + no recommendations.
- **Red-team**: quarterly prompt-injection/never-infer battery from §8 adversarial set.

## 10. Acceptance criteria (pilot sign-off)

1. Eval gate ≥90% on all §8 datasets (incl. glossary), pinned versions, green in CI.
2. Safe-completion on adversarial-never-infer: 100% hard-refuse on cert/full-text/
   licence-guarantee/lab-result/legal-binding subsets; withdrawn cases must warn with
   NO recommendation (warn ≠ refuse — matches current eval semantics for IDs 44/45);
   zero tolerated recommendations of withdrawn IS; zero citation-verifier trips on gold.
3. Every answer shows IS+year+status+section/source-snippet+source URL+last-checked;
   withdrawn IS never recommended.
4. EN+HI parity: multilingual set within 5 pts of EN score.
5. DPDP: consent receipts, `DELETE /me` (profile+threads+messages+feedback, tombstone-only
   audit) ≤24 h, purge job verified, erasure E2E asserts grep-clean logs + rows gone.
6. p95 `/chat` <2 s; uptime 99.5% over 14-day pilot window.
7. BIS reviewer approves KB snapshot + 50 sampled live answers (sampling rubric in Phase 7).
8. Rollback: previous KB snapshot restorable in <15 min; runbook tested.
9. Five canonical MSME journeys (§9) pass end-to-end with citations + disclaimer.

---

## 11. Phased build (dependency order; each step cold-startable)

- **Phase 0 — Foundations & guardrails** (no deps)
  Brief: repo hygiene, CI, secrets, DPDP policy doc. Tasks: branch/PR workflow + CI
  (tests+eval gate), `config.yaml` for thresholds, `docs/privacy-policy.md` (DPDP mapping),
  secret handling (no keys in repo). Verify: `pytest/unittest` + `eval/run_eval.py` green in CI.
  Exit: CI red-blocks merges; privacy doc reviewed. Rollback: revert commit.
- **Phase 1 — Versioned KB + ingestion** (dep: 0)
  Brief: migrate flat JSON → SQLite with §2 schema + snapshot/diff crawler scaffolding
  (fixtures first, live crawl behind flag). Tasks: schema + migration script, importer for
  current JSON, snapshot/diff module, supersession + QCO fields, review-queue CLI.
  Verify: round-trip import reproduces current answers; diff detects fixture changes.
  Exit: KB version `v1` published from reviewed snapshot. Rollback: keep JSON fallback.
- **Phase 2 — Retrieval v2 + citation verifier** (dep: 1)
  Brief: BM25 scorer behind feature flag with current scorer as baseline; implement
  verifier (claim↔row mapping, IS-number cross-check). Tasks: scorer module + A/B eval
  report, verifier + `citation_fail_total` metric, thresholds to `config.yaml`.
  Verify: eval gate green on both scorers; verifier trips 0 on gold, 100% on fault-injection.
  Exit: verifier enforced in response path. Rollback: flag off.
- **Phase 3 — API hardening + server threads** (dep: 1, 2)
  Brief: FastAPI migration, server-side threads, auth/rate-limit, redacted logging,
  request IDs, DPDP endpoints. Tasks: endpoint set (§5), rate limiter, thread store with
  TTL, consent/erasure endpoints, OpenAPI schema. Verify: contract tests + load smoke.
  Exit: old stdlib server removed; UI/CLI on new API. Rollback: keep old module one release.
- **Phase 4 — Privacy & access control** (dep: 3)
  Brief: consent ledger, purge jobs, role matrix (§6), 2-person publish, audit log.
  Tasks: purge scheduler, `DELETE /me` E2E, admin auth, redaction audit (grep logs for PII).
  Verify: erasure E2E test; red-team PII probe set clean. Exit: privacy doc sign-off.
  Rollback: disable accounts to admin-only.
- **Phase 5 — UI production** (dep: 3; parallel with 4)
  Brief: feedback buttons, admin diff-review screen, export, a11y pass, Hindi QA.
  Tasks: feedback API wiring, admin screens (auth-gated), snapshot tests, keyboard/
  contrast audit. Verify: `tsc`+build+contract fixtures green; a11y checklist signed.
  Exit: console usable by non-technical BIS reviewer. Rollback: previous `dist/`.
- **Phase 6 — Observability** (dep: 3; parallel with 4–5)
  Brief: structured logs, metrics, alerts, trace sampling (§7). Tasks: log middleware,
  metrics endpoint, alert rules, dashboard JSON. Verify: fault-injection fires alerts.
  Exit: on-call runbook written. Rollback: n/a (additive).
- **Phase 7 — Eval datasets v2 + CI gate** (dep: 2; parallel with 4–6)
  Brief: build §8 datasets (≥225 items), pin versions, human review queue.
  Tasks: dataset authoring + review, harness per-dimension reports, CI gate job.
  Verify: gate green; adversarial 100% refusal. Exit: `eval/datasets/v2` tagged.
  Rollback: gate pins v1.
- **Phase 8 — Pilot hardening** (dep: 4, 5, 6, 7)
  Brief: load test, staleness drill, red-team battery, BIS reviewer sampling (§10.7).
  Tasks: k6 run + tuning, drill + report, fix findings. Verify: §10 criteria 1–6 measured.
  Exit: go/no-go memo. Rollback: full snapshot (KB+config+build) restore runbook.
- **Phase 9 — Pilot launch & handover** (dep: 8)
  Brief: limited rollout, support rota, handover docs. Tasks: runbook, KB refresh rota,
  decisions log update, SIH demo script. Verify: 14-day pilot metrics meet §10.
  Exit: acceptance sign-off. Rollback: §10.8.

Parallelism: 4 ∥ 5 ∥ 6 ∥ 7 after phase 3 with frozen API schema and migration
ownership (4: privacy tables, 6: metrics-only additive tables, 5/7: no server code until
rebase). After EACH parallel merge: contract tests + load-smoke re-green before the next
merge lands. Phase 6 ships behind a feature flag, not "additive, no rollback".

## 12. Risks & mitigations
| Risk | Mitigation |
|---|---|
| BIS portal structure changes break crawler | Fixture-based parser tests; last-good snapshot keeps serving; staleness alert |
| QCO status misread → wrong compulsory advice | QCO fields require human review before publish; answers hedge + link |
| Hindi quality lags EN | Parity criterion (§10.4); dedicated multilingual dataset |
| PII leak via logs/exports | Redaction middleware + log-grep CI check + erasure E2E |
| Scope creep (any of: full-text IS reader, licence-form autofill, lab booking/payments, 22-language coverage, offline mode) | Brief §12 exclusion list enforced at every phase-planning checkpoint |

## 13. Review gate & register

- [x] Adversarial review (blueprint phase 4): independent pass over completeness,
      dependency correctness, decision `#1–#11` compliance — findings fixed below.
- [x] Findings (22: 5 Critical, 12 Major, 5 Minor — all addressed):
      C1 phase-2/7 dataset inversion → phase-2 gate pinned to v1 + A/B report;
      C2 PII stored before consent ledger → consents + TTL moved into phase 3 exit;
      C3 thread ownership + missing export → owner tokens + `GET /me/export` + denial tests;
      C4 phase-8 omitted §10.7–10.8 → verify covers criteria 1–9 with timed drill;
      C5 "100% refusal" vs warn-semantics → §10.2 safe-completion split.
      Majors: §2 schema fields (QCO/section/snippet), §10.3 section restored, glossary
      dataset + gate, `info_pages` table, journey-E2E + criterion #9, parallelism with
      migration ownership + flag rollback, erasure scope + redacted-at-write, seeded-PII
      log-grep, measurable exits, `KB_BACKEND` flag rollback, auth/2-person/moderation
      design, metric SLOs + pre-sampling redaction. Minors: KB size wording, `web/`
      removal in phase 5, all five exclusions, thread_id contract freeze, eval
      methodology (sources, sign-off, metric definitions, reference env).
- [ ] Register: plan saved here; `docs/decisions.md` row #12 (plan approved) on sign-off.
