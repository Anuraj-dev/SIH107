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

**Grill method:** grill-me, one question at a time, 9 areas covered. No implementation started.
