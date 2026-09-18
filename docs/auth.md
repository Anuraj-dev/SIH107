# Auth design (Phase 4) — pilot decision record

## Choice: scoped API keys now, SSO later
- Admin endpoints (`GET /kb/diff`, `POST /kb/publish`) require `X-Admin-Key`.
  Keys are provisioned out-of-band, stored as env `BIS_ADMIN_API_KEYS` (comma-separated),
  hashed (SHA-256) in-process, never logged.
- Publish additionally requires TWO distinct admin keys per request
  (`publisher_key` ≠ `approver_key`), enforced by app + `kb_reviews` CHECK constraint.
- Rotation SOP: add new key → deploy → verify old-key 403 → remove old key.
  Emergency revocation = restart with key removed from env.
- SSO (provider TBD at pilot scale-up) replaces static keys; endpoint shapes unchanged.

## Registered MSME tier
- `users(key_hash, tier)`; issuance is currently manual (admin CLI in Phase 9 runbook).
  OTP-based self-registration is DESIGNED but deferred: flow = phone OTP → `users` row
  (tier=registered, 300 req/h) → key delivered once. No OTP vendor is integrated in pilot.
- Anonymous tier stays fully functional within 30 req/h + burst caps.

## What admins can/cannot see
- CAN: pending KB diffs, audit tombstones, aggregate metrics (Phase 6).
- CANNOT: raw query text (only `text_redacted`), user PII (export is self-service only).
