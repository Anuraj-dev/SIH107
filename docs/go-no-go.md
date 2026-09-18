# Go / No-Go memo — BIS Assistant pilot
_Date: 2026-09-18 | Datasets pinned: `eval/gold.json` (v1), `eval/datasets/v2` (v2)_

## §10 criteria measurements
| # | Criterion | Result |
|---|---|---|
| 1 | Eval gate ≥90% all datasets, CI green | v1 52/52, v2 267/267 (all dims 100%), `pytest` 54 green |
| 2 | Adversarial safe-completion; 0 withdrawn recommendations; 0 verifier trips on gold | 44/44 safe; 0 trips after 52 gold answers |
| 3 | IS+year+status+section+URL+last-checked on every answer | Enforced by `format_citation` + verifier; v1 `section_ref` empty → clause text refused by construction |
| 4 | EN+HI parity within 5 pts | delta 0.0 pts (100/100) |
| 5 | DPDP: receipts, `DELETE /me` ≤24h, purge, erasure E2E | Tested (`test_api_contract`, `test_privacy_probes`); purge scripted |
| 6 | p95 <2 s | 791 ms @ 200 req/20 conc (in-process, reference class) |
| 7 | BIS reviewer: KB snapshot + 50 sampled answers | PENDING — requires human reviewer (rubric: `eval/datasets/v2/README.md`) |
| 8 | Restore <15 min, runbook tested | 1.2 s measured (copy + shadow + gate); runbook `docs/runbook.md` |
| 9 | 5 MSME journeys E2E | 5/5 green (`tests/test_journeys.py`) |

## Residual risks
- No generic jailbreak detector (v2 jailbreaks wrap real triggers; caught today).
- KB is 15 real IS + samples; QCO flags `unknown` pending human review — answers hedge.
- 14-day uptime window starts at pilot launch, not yet observed.

## Decision: **GO (conditional)** — launch pilot pending criterion #7 human sign-off.
