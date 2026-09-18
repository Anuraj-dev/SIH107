# Privacy Policy (DPDP Act 2023 mapping) — BIS Assistant pilot
_Date: 2026-09-18 | Owner: TBD (named owner required at Phase-4 exit)_

## Data we collect
| Data | Purpose | Basis | Stored where |
|---|---|---|---|
| Chat queries (redacted) | Answer + improve retrieval | Consent (chat use) | `threads`/`messages`, logs |
| Business profile (firm, city, product, phone/email) | Personalise licensing guidance | Explicit opt-in (`POST /consent`) | `profiles` |
| Feedback ratings | Quality measurement | Legitimate use, anonymised | `feedback` |
| Admin audit events | Security | Legal obligation | `audit_log` (tombstones post-erasure) |

We never store: test reports (session-only), Aadhaar/government IDs, consumer sensitive PII
beyond what is needed to answer.

## Principal rights (how to exercise)
- **Access**: `GET /me/export` (self-service, owner token).
- **Correction**: resubmit profile fields; latest write wins.
- **Erasure**: `DELETE /me` or say "delete my data" — profile + threads + messages +
  feedback deleted ≤24 h; audit keeps `{actor, action, at}` tombstone only.
- **Grievance**: contact listed at pilot launch (Phase 9); response SLA 7 days.

## Retention
Threads/messages: 90 days, then purged. Consent receipts: life of account + 3 years
(statutory). Backups: erasure propagates within 30 days.

## Children
No accounts under 18; Standards-Club content is informational only.

## Breach notification
Material breaches notified to the Board and affected principals per DPDP timelines;
runbook: `docs/runbook.md` (Phase 6+).
