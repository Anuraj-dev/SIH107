# On-call runbook — BIS Assistant pilot
_Owner: pilot rota (Phase 9 names names). Dashboards: `ops/dashboard.json`; alerts: `ops/alerts.yaml`._

## Triage (any page)
1. `curl 127.0.0.1:8000/health` and `/metrics`; note `X-Request-ID` of failing call.
2. Check `bis_chat_5xx_total`, `bis_citation_fail_total`, `bis_kb_staleness_days`.
3. Logs are JSON (`bis.api`, `bis.verifier`); query text is pre-redacted — never paste raw PII into tickets.

## Playbooks
- **citation-trips**: verifier refused an answer. Pull `violations` from log, reproduce via CLI,
  fix KB row or scorer, re-run eval gate before redeploy. Any trip pages — treat as P1.
- **refusal-swing**: >10 pts/hour. Cause is usually a KB refresh or threshold change:
  diff last KB snapshot (`ingest.review list`), check `config.yaml` history.
- **kb-refresh**: staleness >14 days. Run crawl fixtures → `pending_diffs` review →
  2-person `POST /kb/publish`. Never publish unreviewed.
- **latency**: p95 >2 s/5 min. Check load, restart uvicorn workers, scale reference env
  (2 vCPU/4 GB). Roll back last deploy if correlated.
- **errors**: 5xx on /chat. Request ID → logs → fix → contract tests → redeploy.
- **feedback**: neg share >15%/day. Sample `feedback(status=pending)` in review queue,
  convert to eval items (Phase 7 intake).

## KB snapshot restore (<15 min, acceptance §10.8)
1. `cp kb/bis.db kb/bis.db.bad-$(date +%s)`; restore last-good: `cp kb/snapshots/bis-YYYYMMDD.db kb/bis.db`
   (nightly copy job, Phase 9 rota).
2. Restart API; run `eval/run_eval.py` + `scripts/kb_shadow_compare.py`; both green → done.
3. Record incident in decisions log.

## Rollback map
- Phase 1 KB: `KB_BACKEND=json` (shadow-compared).
- Phase 2 scorer: `BIS_RETRIEVAL_SCORER=keyword`.
- Phase 3 server: previous uvicorn build (old stdlib `api.py` retained one release).
- Phase 6 metrics: `BIS_METRICS_ENABLED=false`.
- Full: KB snapshot + `config.yaml` + build tag restore (Phase 8 drill).

## Erasure / breach
- `DELETE /me` SLA 24 h; verify with export call. Material breach: notify Board +
  affected principals per DPDP timelines; see `docs/privacy-policy.md`.
