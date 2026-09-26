# BIS Standards & Services Assistant (MVP)

Conversational BIS assistant. Retrieval uses allowlisted BIS metadata and the checked-in
BIS gazette/product-manual corpus. Paid full-standard text is excluded.

Coverage: 16 curated rows (15 real + 1 withdrawn demo) in `data/*.json` +
breadth tier (~22,471 list-level metadata rows) via `scripts/breadth_crawl.py`
into SQLite. Curated scope/keywords/slots stay authoritative; breadth rows carry
`qco_status=unknown`, no clause refs.

## Run backend (stdlib only, Python ≥3.10)
```
pip install -r requirements-dev.txt
PYTHONPATH=src python -m bis_assistant.cli
PYTHONPATH=src python -m bis_assistant.api   # POST /chat on :8000 (thread_id + X-Owner-Token)
PYTHONPATH=src python -m pytest tests/ -q
```
Stdlib-only subset (no pytest): `PYTHONPATH=src python -m unittest tests.test_assistant -v`.

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

## Chat answer contract
- Every valid chat turn is answered by the configured LLM, using retrieved lab passages as context.
- The model writes the answer. Retrieved passages are never shown as a substitute answer.
- If the model is missing or fails, `/chat` returns a clear model-unavailable message.
- The system prompt requires evidence-only BIS claims, source citations, no invented clauses or status, and natural clarifications instead of fixed slot questions.
- The model can answer its name and current India date/time from trusted runtime context. Other unrelated questions receive a model-written scope refusal.

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
`/chat` retrieves from these BIS source chunks. Retrieval starts with exact IS matching and SQLite
FTS5/BM25. An optional local sentence-transformers index adds dense search and
reciprocal-rank fusion; an optional CrossEncoder reranks the candidates. The
LLM synthesizes an answer from the selected passages. There is no metadata,
extractive, or raw-passage answer path. If no LLM is configured or generation
fails, the app returns the model-unavailable state.

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
`corpus_documents` (raw text kept), `corpus_chunks`, `corpus_embeddings`,
`catalogue_standards`, and the `corpus_chunks_fts` FTS5 index over chunk text,
standard number, document type and heading. The default import does not download
ML models. Reimport with the same `--embedding-model` value to rebuild dense
vectors; a corpus reimport without that option clears the old vectors.

Dense retrieval uses the optional `sentence-transformers` dependency and the
configured English model `BAAI/bge-small-en-v1.5`. The application only loads
models from the local Hugging Face cache; it never downloads a model during
startup or chat retrieval. Without the optional package, cached model, or a
matching dense index, chat continues with FTS/lexical retrieval.

Install the optional dependency and explicitly build the index. This command
may download the model if it is not already cached:

```
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install 'sentence-transformers>=3.0'
PYTHONPATH=src python scripts/import_rag_corpus.py \
  --corpus new_data/bis-rag-text-corpus-2026-09-18 \
  --db kb/bis_rag.db \
  --embedding-model BAAI/bge-small-en-v1.5
```

The first command installs the CPU-only PyTorch wheel; run it before installing
`sentence-transformers` so pip reuses that wheel.

The command reports an embedding warning and leaves the imported corpus usable
for lexical retrieval if optional model loading or vector generation fails.
Set `BIS_RAG_EMBEDDING_MODEL` to the same model when starting the API (or keep
the config default). If configuring `BIS_RAG_RERANKER_MODEL`, that model must
also already be present in the local cache. Dense search uses the SQLite vector
table; no separate vector service is required. See the
[BGE-small English model card](https://huggingface.co/BAAI/bge-small-en-v1.5)
for model details.

### 2. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `BIS_RAG_ENABLED` | `1` | `0` to disable lab retrieval |
| `BIS_RAG_DB_PATH` | `kb/bis_rag.db` | SQLite corpus index |
| `BIS_RAG_TOP_K` | `5` | evidence chunks per query |
| `BIS_RAG_SEMANTIC` | `1` | use dense search when the matching index exists |
| `BIS_RAG_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | model name used to build and query the dense index; loaded cache-only at runtime |
| `BIS_RAG_RERANKER_MODEL` | empty | optional CrossEncoder model for final reranking |
| `BIS_LLM_PROVIDER` | `openai-compatible` | `ollama`, `openai-compatible`, `gemini`, or `anthropic` |
| `BIS_LLM_MODEL` | empty | provider model id; empty makes the chatbot unavailable |
| `BIS_LLM_API_KEY` | empty | required for cloud APIs; keep it in ignored `.env` |
| `BIS_LLM_BASE_URL` | provider default | local server or cloud API endpoint |
| `BIS_LLM_TIMEOUT_S` | `10` | request timeout in seconds; local models may need more |

Same keys exist as `rag:`/`llm:` sections in `config.yaml`
(env `BIS_<SECTION>_<KEY>` wins). Copy `.env.example` to `.env`, uncomment one
provider block, then load it before starting the API with
`set -a; source .env; set +a`.

For Ollama, set `BIS_LLM_PROVIDER=ollama`, `BIS_LLM_MODEL` to a pulled model,
and `BIS_LLM_BASE_URL=http://localhost:11434`. LM Studio works through
`openai-compatible` with a base URL such as `http://localhost:1234/v1`; local
servers on localhost do not need an API key. For cloud APIs, set the provider,
model, endpoint when needed, and secret key in `.env`, then export those values
before starting the API. OpenAI and Groq use `openai-compatible`; Anthropic and
Gemini have native adapters. Provider errors return an explicit offline notice.

Groq's Qwen 3.8 27B adapter uses instruct mode for interactive answers. To run
the repository's 50-question live-provider acceptance set, configure the Groq
block above and run:

```
BIS_EVAL_ALLOW_ENV=1 PYTHONPATH=src .venv/bin/python eval/run_groq_50.py
```

### 3. Run the app on the corpus index

```
export BIS_RAG_DB_PATH=kb/bis_rag.db BIS_RAG_TOP_K=5
PYTHONPATH=src python -m bis_assistant.api        # stdlib POST /chat on :8000
# or: uvicorn bis_assistant.server:app --port 8000  # FastAPI server + threads
```

Responses carry `citations[]` plus `sources[]`/`rag_evidence[]`
(`standard_number`, `title`, `url`, `doc_type`, `heading`, `chunk_text`,
`score`), `rag_mode`, `rag_used_llm`, and `model_available`. Successful answer
text is always generated by the LLM. The React console types
(`ui/src/types.ts`) include these fields.

### 4. Example corpus-backed queries

- "What does IS 101 (Part 2/Sec 6):2026 cover? formaldehyde" → LLM synthesis
  grounded in the matching gazette chunk with source citations.
- "IS 14478 plain bearings product manual scope" → product-manual chunks
  (classification, packing/marking) with the BIS object-storage source URL.
- "thick-walled bushes plain bearings specification" → keyword retrieval
  from the known `IS 14478:2026` manual (no IS number in the query).
- "What is your name?" and "What time is it?" → LLM answers from runtime
  identity/time context, not its training memory.
- "steel bottle" → the LLM answers or asks a natural, query-specific question
  using the lab evidence. There are no predefined slot questions.
- Out-of-scope questions → the LLM gives a brief scope refusal.

### 5. Tests

```
.venv/bin/python -m pytest tests/test_rag.py tests/test_sih_gaps.py -q
.venv/bin/python -m pytest tests/test_assistant.py tests/test_retrieval_v2.py tests/test_config.py tests/test_kb.py -q
BIS_EVAL_ALLOW_ENV=1 PYTHONPATH=src .venv/bin/python eval/run_groq_50.py  # configured LLM required
```
