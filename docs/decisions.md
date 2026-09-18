# Decisions Log — BIS Assistant Grill
_Date: 2026-09-18_

| # | Area | Decision | Rationale | Risk / Follow-up |
|---|------|----------|-----------|------------------|
| 1 | Target users | Primary = MSMEs + startups | Highest certification pain, SIH impact; can't optimize for all | Keep consumer/student paths degraded but not broken |
| 2 | Data access | Only `bis.gov.in/know-your-standard` + public BIS metadata; broad scrape REJECTED | Copyright on full IS text; third-party PDFs stale/illegal | Enforce allowlist crawler; link to e-sale for full text |
| 3 | Scrape pivot | Initial "scrape everything" → narrowed to Know-Your-Standard after challenge | User agreed: grounded answers via clarifying Qs, not bulk scrape | Documented to prevent regression to broad scrape |
| 4 | Citations | Strict: IS + year + status + section + URL + last-checked; refuse if missing | Brief requires doc/clause refs; blocks hallucinated IS numbers | Know-Your-Standard may lack clause depth → cite visible scope + link out, never invent |
| 5 | Recommendation safety | Ranked candidates + confidence + disclaimer + clarifying questions; never single definitive | Wrong IS = wrong manufacturing; safety-critical | Need question templates per product category |
| 6 | Multilingual | EN + Hindi MVP | Covers brief, demo-able, eval-feasible | Design i18n keys for later expansion |
| 7 | Versioning | Year + status (active/superseded/withdrawn) + last-checked on every rec | IS revisions (e.g. IS 10500) make number-only answers dangerous | Need refresh job + supersession mapping |
| 8 | Privacy | Store business PII for personalization | User explicitly chose over session-only | HIGH: requires DPDP consent, minimization, retention + deletion; define before build |
| 9 | Evaluation | Gold 50+ Q/A, groundedness + refusal rate, >90% ship gate + plain-language glossary check | Fluency-only eval hides hallucinations; users lack standards vocab | Build dataset before any model work |
| 10 | Never-infer | Strict list: no certified/compliant claims, no verbatim clauses, no licence guarantees, no invented labs; refuse + redirect | Legal/safety boundary | Encode as system prompt + tests |
| 11 | Multi-turn grounding | Vague query → ask ≤2 discriminative Qs/turn until context suffices; no IS naming until grounded; max 2 rounds then answer with stated assumptions | Wrong IS = wrong manufacturing; single-shot guesses unsafe | Slots in `slots.py`; thread ctx over API/CLI/UI; 6 new tests; eval single-shot force fallback |
| 12 | Production plan approved + implemented (Phases 0–9) | `docs/implementation-plan.md` built in full: versioned SQLite KB, BM25 flag, citation verifier, FastAPI + server threads, DPDP endpoints, metrics/alerts, v2 eval (267), journey E2E, go-no-go conditional GO | Pilot readiness with measured acceptance | Human sign-off pending: BIS reviewer sample (§10.7), 14-day uptime window |
| 13 | Breadth coverage (16 → ~22,471 metadata rows) | Lawful P0-only pipeline (`ingest/breadth.py`, `scripts/breadth_crawl.py`): DG-dashboard DataTables lists + KYS detail (on-demand) + CRS QCO seed + LIMS per-IS lookup. Research in `docs/data-sources-research.md` (VERIFIED/PARTIAL/BLOCKED, 2026-09-18). e-sale stays BLOCKED (robots), manakonline gated. Part-aware IS keys; curated rows stay authoritative (breadth colliding with curated depth is skipped); QCO still human-reviewed; JSON backend stays default with SQLite-empty fallback | Closes 0.07% gap without violating #2/#3 | Reviewer batch-publish (`approve-all`, distinct publisher+approver); new-portal post-Oct-2025 records need Playwright spike (§5 Q1) |

**Grill method:** grill-me, one question at a time, 9 areas covered. No implementation started.
