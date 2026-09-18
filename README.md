# BIS Standards & Services Assistant (MVP)

Conversational assistant per `docs/product-brief.md`. Retrieval **only** from allowlisted BIS metadata
(`bis.gov.in/know-your-standard`, DG dashboard, CRS, LIMS, manakonline). No scraped full-text PDFs.

Coverage: 16 curated rows (15 real + 1 withdrawn demo) in `data/*.json` +
breadth tier (~22,471 list-level metadata rows) via `scripts/breadth_crawl.py`
into SQLite — see `docs/data-sources-research.md`. Curated scope/keywords/slots
stay authoritative; breadth rows carry `qco_status=unknown`, no clause refs.

## Run backend (stdlib only, Python ≥3.10)
```
PYTHONPATH=src python -m bis_assistant.cli
PYTHONPATH=src python -m bis_assistant.api   # POST /chat on :8000
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python eval/run_eval.py        # gate: >=90%
```

## Run browser UI (TypeScript + React, in `ui/`)
```
cd ui && npm install && npm run dev   # http://127.0.0.1:5173, /api proxied to :8000
```
Keep the Python API running on :8000 first. Test console: sample queries (EN/Hindi/refusal),
citations panel, answered/refused + PII badges, raw-JSON toggle, EN/HI switch.
Phase 5 adds: per-answer 👍/👎 (fixture-driven until `POST /feedback` ships), "known so far"
chips + assumptions banner, redacted conversation export, token-gated admin KB diff-review
screen, WCAG-AA pass (see `ui/A11Y.md`), and contract fixtures (`npm run test:contract`).

## UI console
The React console in `ui/` is the only frontend (the legacy static `web/` page was removed).

## Design vs grill decisions
- Ranked candidates + confidence + clarifying Qs, never single definitive IS (`src/bis_assistant/assistant.py:1`)
- Strict citations `IS:year [status, last-checked] + URL` (`src/bis_assistant/retriever.py:format_citation`)
- Never-infer refusals + disclaimer (`src/bis_assistant/safety.py`)
- EN+HI (`src/bis_assistant/i18n_privacy.py`), DPDP consent/minimisation/delete
- Version/status on every rec; Withdrawn entries warn

## Demo queries
- "steel water bottle vacuum flask which IS?"
- "LED bulb manufacturing, CRS needed?"
- "How to verify gold HUID?"
- "नल के पानी का मानक कौन सा है?"

## Full-text RAG corpus (BIS gazettes + product manuals)

The `new_data/bis-rag-text-corpus-2026-09-18` snapshot holds 359 extracted
TXT documents plus `data/standards_metadata.ndjson` (~24k catalogue rows),
`data/standard_documents.ndjson` (attachment provenance),
`data/files.ndjson` (public attachment URLs) and the conversion manifests.
When enabled, `/chat` retrieves from **both** the curated metadata KB and
these full-text chunks (hybrid exact-IS boost + SQLite FTS5/BM25 + semantic
rerank), and answers from the retrieved passages. The deterministic metadata
mode stays as fallback; without LLM credentials the answer is extractive
(best passages + sources) rather than a failure.

### 1. Ingest the corpus

```
PYTHONPATH=src python scripts/import_rag_corpus.py \
  --corpus new_data/bis-rag-text-corpus-2026-09-18 \
  --db kb/bis_rag.db
```

Expected output: `imported 359 documents, ~4292 chunks, 24133 catalogue rows`.
Re-running is idempotent per `source_file`. Every TXT is preserved — files
without a manifest match keep blank provenance instead of being dropped.
Part/section designations (e.g. `IS 101 (Part 2/Sec 6)` vs
`IS 101 (Part 5/Sec 1)`) stay distinct catalogue rows. Tables created:
`corpus_documents` (raw text kept), `corpus_chunks`, `catalogue_standards`,
plus the `corpus_chunks_fts` FTS5 index over chunk text, standard number,
document type and heading.

### 2. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `BIS_RAG_ENABLED` | `0` | `1` to serve corpus answers in `/chat` |
| `BIS_RAG_DB_PATH` | `kb/bis_rag.db` | SQLite corpus index |
| `BIS_RAG_TOP_K` | `5` | evidence chunks per query |
| `BIS_RAG_SEMANTIC` | `1` | semantic rerank channel (`0` = lexical only) |
| `BIS_RAG_EMBEDDING_MODEL` | empty | optional sentence-transformers model (stdlib hashed vectors otherwise) |
| `BIS_LLM_MODEL` | empty | e.g. `gpt-4o-mini`; empty = extractive fallback |
| `BIS_LLM_API_KEY` | empty | secret — env only, never committed |
| `BIS_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `BIS_LLM_TEMPERATURE` / `BIS_LLM_MAX_TOKENS` / `BIS_LLM_TIMEOUT_S` | `0.2` / `512` / `20` | generation settings |

Same keys exist as `rag:`/`llm:` sections in `config.yaml`
(env `BIS_<SECTION>_<KEY>` wins). See `.env.example`.

### 3. Run the app on the corpus index

```
export BIS_RAG_ENABLED=1 BIS_RAG_DB_PATH=kb/bis_rag.db BIS_RAG_TOP_K=5
PYTHONPATH=src python -m bis_assistant.api        # stdlib POST /chat on :8000
# or: uvicorn bis_assistant.server:app --port 8000  # FastAPI server + threads
```

Responses carry `citations[]` plus `sources[]`/`rag_evidence[]`
(`standard_number`, `title`, `url`, `doc_type`, `heading`, `chunk_text`,
`score`) and `rag_mode`/`rag_used_llm`. The React console types
(`ui/src/types.ts`) include these fields.

### 4. Example corpus-backed queries

- "What does IS 101 (Part 2/Sec 6):2026 cover? formaldehyde" → gazette
  schedule row + title (extractive passages, `IS 101…` citations).
- "IS 14478 plain bearings product manual scope" → product-manual chunks
  (classification, packing/marking) with the BIS object-storage source URL.
- "thick-walled bushes plain bearings specification" → keyword retrieval
  from the known `IS 14478:2026` manual (no IS number in the query).
- "Give me the full text summary of IS 14478 plain bearings scope" →
  full-text refusal is superseded by corpus evidence when RAG is on;
  generic "give me the full verbatim text" with no evidence still refuses.
- Curated flows are unchanged: "steel bottle" still clarifies, vacuum-flask
  details still answer `IS 17803`, HUID/lab/scheme journeys untouched.

### 5. Tests

```
.venv/bin/python -m pytest tests/test_rag.py tests/test_sih_gaps.py -q
.venv/bin/python -m pytest tests/test_assistant.py tests/test_retrieval_v2.py tests/test_config.py tests/test_kb.py -q
.venv/bin/python eval/run_eval.py   # gate >=90% (currently 100%)
```

## SIH requirement audit (image table verdicts → fixes)

| Requirement | Verdict | Fix in this repo |
|---|---|---|
| AI-powered conversational assistant | **True** — only OpenAI-compatible LLM path existed | `BIS_LLM_PROVIDER=openai-compatible\|gemini\|ollama` with provider payloads/auth, retries (`BIS_LLM_RETRIES`), tested with mocked transport; extractive fallback unchanged |
| Natural language understanding | **True** — regex/keyword only | New `src/bis_assistant/nlu.py`: scored intent classifier (lexical phrases + structural IS/question cues + history continuity) + entities (IS numbers, product terms, stage); exposed as `intent`/`intent_confidence` in `/chat` payload, `Turn`, and UI types |
| Context-aware responses | **True (partial)** — slots only | New `memory.py`: extractive thread summary (`context_summary` in payload) + history-aware query expansion for corpus/catalogue retrieval; curated routing untouched |
| Source-backed info | Good — keep | Untouched; catalogue answers reuse the same citation + disclaimer contract |
| Answer questions on Indian Standards | **Fixed earlier** via corpus RAG; full paid-standard text stays out for copyright reasons | Plus 24k catalogue search (`catalogue_search.py`) so title/department/committee answers work beyond the 359 indexed docs |
| Recommend standards for novel products | **True** — 16 hardcoded rows | Catalogue fallback (`catalogue_answer`) when curated is ungrounded and the scan is strong; single-generic-word collisions (metal "iron" vs appliance "iron") no longer hijack via `_strongly_grounded` tie-break; gibberish still refuses |
| BIS certification guidance | **True** — static templates | Adaptive `guidance.py`: "For your situation" next steps from stage (new/renewal/import/manufacture/export) + user product terms + cited scheme's next step; verifier-safe (no new IS numbers/`clause`); `BIS_GUIDANCE_ADAPTIVE=0` restores pure templates |
| Explain certification processes | **True** — same cause | Same composer; scheme steps + user-tailored pointer |
| Consumer-related queries | **True (limited)** — templates kept deliberately | Routed via `consumer_query` intent; factual templates unchanged (no invented policies) |
| Hallmarking guidance | Template-only by design | Unchanged deterministic HUID flow + `hallmarking` intent label |
| Testing lab suggestions | Links-only by design (no live LIMS offline) | Unchanged LIMS flow + `lab_suggestion` intent label |
| Multilingual support | **True** — EN/HI dicts only | LLM translation API (`translate.py`, any provider) with dictionary fallback; extended Hinglish/Devanagari BIS vocabulary (`taar`→wire, `balb`→bulb, `helmat`→helmet, `tayar`→tyre, `loha`→steel, `तार`→wire, `बल्ब`, `हेलमेट`, `सीमेंट`, …) |

New response fields (all optional/backward-compatible): `intent`,
`intent_confidence`, `context_summary`, `guidance_adaptive`.
