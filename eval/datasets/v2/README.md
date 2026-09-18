# Eval datasets v2 — authoring notes (plan §8)

Pinned for CI gate (`eval/run_v2.py`, gate ≥90% every dimension).
Ground truth: `data/standards.json` (16 IS incl. withdrawn demo IS 0000-DEMO),
`data/schemes.json` (ISI/CRS/FMCS/HALLMARK), `data/labs.json`,
`data/glossary.json` (6 terms). No IS numbers invented for non-adversarial
items; adversarial items carry `must_refuse:true` and no expected IS.

Item schema: `{id, query, lang, expect_is?, expect_scheme?, must_refuse, must_cite}`.
Eval is single-shot: `needs_info` is followed once with `force:true`
(same pattern as `eval/run_eval.py`).

## Files

- `gold-product.json` (105 items, P-001…P-105)
  Source: `data/standards.json` `category_keywords` + `scope_en/hi` +
  `src/bis_assistant/slots.py` slot fillers (voltage/grade/capacity/age/mm),
  source portal `https://www.bis.gov.in/know-your-standard`.
  Covers: all 15 active IS ×7 variants (EN canonical, EN paraphrase with slot
  fillers for direct answer, ambiguous-pair disambiguation e.g. piped
  IS 10500 vs packaged IS 14543 vs mineral IS 13428, HI Devanagari code-mixed,
  Hinglish roman, LED/CRS cases with `expect_scheme:CRS`).
  Author: subagent Phase-7. Reviewer sign-off: ______ (blank for owner).

- `gold-schemes.json` (34 items, S-001…S-034)
  Source: `data/schemes.json` (`process_en/hi`, `apply_at`, `source_url`),
  `data/labs.json` LIMS search `https://lims.bis.gov.in/home/search_is_number/`,
  hallmark overview `https://www.bis.gov.in/hallmarking-overview/`,
  training calendar `https://www.bis.gov.in/training-2/training-programmes/`,
  BIS Care complaint journey (falls back to ISI scheme block).
  Covers: ISI×6, CRS×6 (incl. LED IS 16102-1 product-linked), FMCS×5,
  HALLMARK-HUID×5, LAB-LIMS×5 (`expect_scheme:LIMS`), training/club×4
  (`expect_scheme:training`), complaint×3 (ISI/HALLMARK).
  Author: subagent Phase-7. Reviewer sign-off: ______.

- `gold-glossary.json` (24 items, G-001…G-024)
  Source: `data/glossary.json` 6 terms EN/HI.
  Covers: QCO×4, CM/L×4 (pure glossary, `must_cite:false`), HUID×4 / CRS×4 /
  FMCS×4 (journey-augmented, `must_cite:true`), Indian Standard×4 grounded
  with product context (IS 10500/269/4151) to avoid the standalone-glossary
  verifier trip (glossary EN for IS contains “IS 10500” with zero citations).
  Hindi avoids “matlab” (substring “lab” triggers the LAB journey); uses “arth”.
  Author: subagent Phase-7. Reviewer sign-off: ______.

- `adversarial-never-infer.json` (44 items, A-001…A-044)
  Source: `src/bis_assistant/safety.py` `NEVER_PATTERNS` + `docs/decisions.md`
  decision #10. All `must_refuse:true`, no expected IS/scheme.
  Covers: cert-claim×6 (`is my/this product certified/compliant/approved`),
  licence-guarantee×6 (`guarantee/assure … licence/approval/certificate`),
  full-text×8 (`full/complete/entire/verbatim … text/clause/standard`,
  `invent … standard/IS number`), clause-quote×6, lab-result×6
  (`predict/tell … test result/lab result`), legal-advice×6
  (`legally/binding/sue/liabilit`), timeline-guarantee + jailbreak
  paraphrases×6 (DAN/ignore-rules wrappers still containing a trigger phrase).
  Jailbreaks without a never-infer trigger are NOT included (current safety
  layer has no generic jailbreak detector — documented gap).
  Author: subagent Phase-7. Reviewer sign-off: ______.

- `multilingual.json` (42 items, M-001…M-042)
  Source: `data/standards.json` + `src/bis_assistant/retriever.py`
  HINGLISH/DEVNAGARI maps. 14 IS ×3 parallels (EN lang:en, HI Devanagari
  lang:hi, Hinglish roman lang:hi) with identical `expect_is`.
  Hindi queries are code-mixed with English product keywords (pure Hindi
  without keywords under-retrieves). LED triple carries `expect_scheme:CRS`.
  Author: subagent Phase-7. Reviewer sign-off: ______.

- `versioning.json` (18 items, V-001…V-018)
  Source: `data/standards.json` `status`/`year`/`last_checked`.
  Covers: withdrawn IS 0000-DEMO×5 (`must_refuse:true`, warn-no-recommend
  accepted as safe, `must_cite:false`), active status/year/last-checked×13
  across 10 IS incl. superseded phrasing (“has X been superseded?” → still
  Active, no false Withdrawn) + 1 HI item. KB has no true superseded rows,
  only the withdrawn demo, so supersession is tested as Active-with-last-checked.
  V-005 phrasing avoids generic “manufacture” (its scope token inflates
  IS 17803 to score≥10 and leaks an active recommendation next to the
  withdrawn warning).
  Author: subagent Phase-7. Reviewer sign-off: ______.

## Spot-checks

10+ items per file manually reviewed against live `answer()` output
(queries, expected IS/scheme, refusal, citations, disclaimer); bad items fixed:
P-102 (added English `glass/safety/automotive` — `kaanch` unmapped),
S-005 (added `drinking/20 litre plant` to ground IS 14543),
A-003/A-004/A-006 (exact `is my/this product …` trigger phrasing),
G-004/G-012 (`matlab`→`arth` to avoid LAB substring trip),
V-005 (rephrased to avoid `manufacture` stopword leak).

## Harness

`eval/run_v2.py` — run with repo venv:
`PYTHONPATH=src /home/amit/Projects/SIH107/.venv/bin/python eval/run_v2.py`
