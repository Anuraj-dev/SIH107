# BIS Standards & Services Assistant (MVP)

Conversational assistant per `docs/product-brief.md`. Retrieval **only** from allowlisted BIS metadata
(`bis.gov.in/know-your-standard`, CRS, LIMS, manakonline). No scraped full-text PDFs.

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

## Legacy `web/` page
The static `web/` page is legacy and superseded by the React console in `ui/` — do not link to
it for new work. Physical removal is deferred (left untouched to avoid conflicts with parallel
in-flight work); a follow-up will delete `web/` per plan §5.

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
