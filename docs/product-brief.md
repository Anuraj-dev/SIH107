# BIS Standards & Services Assistant — Product Brief
_Date: 2026-09-18 | Status: grilled, agreed, **implemented (MVP verified: 11 tests + 52/52 eval)**_

## 1. Problem
Users (MSMEs, startups, students, consumers) struggle to find applicable Indian Standards, certification requirements, schemes, licensing procedures, testing requirements, and technical answers across fragmented BIS portals/PDFs.

## 2. Solution (from SIH brief)
AI conversational assistant that understands plain language, retrieves from authorized BIS sources only, and answers with source-backed references (document/clause where applicable).

Must support:
- Answer questions on Indian Standards
- Recommend applicable standards from product descriptions (grounded, with clarifying questions)
- Guide on certification schemes + processes (ISI, CRS, FMCS, Hallmarking, etc.)
- Consumer queries, hallmarking/HUID, labs, Standards Clubs/training
- Multilingual interaction
- Plain-language explanations of industry terms (users lack prior standards vocabulary)

## 3. Primary user (MVP)
**MSMEs + startups seeking certification.** End-to-end task: "what IS applies to my product + what scheme + testing + licensing steps" must work even if other journeys degrade.

Secondary (degraded gracefully in MVP): consumers (hallmarking/complaints), students/Standards Clubs (explainers).

## 4. Authorized sources & licensing
- **Allowed:** `https://www.bis.gov.in/know-your-standard` + other public BIS metadata: IS number/title/scope, scheme manuals, licensing process pages, lab directories, FAQs.
- **Forbidden:** broad scraping of third-party IS PDF copies; no bulk reproduction of paid full-text standards.
- Full standard text: link to BIS e-sale/store; never paste verbatim beyond fair snippet shown on authorized page.
- Initial broad-scrape idea was explicitly rejected during grill for copyright + staleness risk.

## 5. Citations (strict)
Every factual claim: `IS number + year/version + status + section shown on source + URL + last-checked date`. If source missing → refuse + redirect, never invent clause numbers.
Tension noted: Know-Your-Standard may not expose full clause text → cite what it shows, link out for full text, never fabricate wording.

## 6. Recommendation safety
- Never give single definitive "your IS is X."
- **Multi-turn grounding (agreed 2026-09-18): vague queries do NOT get a recommendation.**
  Hold the IS naming, ask ≤2 most discriminative questions per turn (per-IS slots in
  `src/bis_assistant/slots.py`), merge follow-up answers into the thread, and answer only on:
  exact IS match, high score (≥15) with margin (≥5), all slots filled, user `force`
  ("answer with assumptions"), or 2 rounds exhausted (then state assumptions explicitly).
  New-topic detection resets the thread; journeys/glossary answer without interrogation.
- Give ranked candidates + confidence + why + what to confirm next.
- Mandatory disclaimer: informational only, confirm with BIS / licensed lab, testing required.
- Never state compliant / certified / approved.

## 7. Multilingual scope (MVP)
**English + Hindi full quality end-to-end with eval.** No 22-language promise for MVP. Architecture must allow later expansion.

## 8. Updates / versioning
Every rec shows year/version + status (active / superseded / withdrawn / under revision) + last-checked date. Stale → warn + refuse to guarantee. Source refresh cadence to be defined in build (Know-Your-Standard re-sync + manual BIS notification check).

## 9. Privacy
Decision: MVP will store business PII (factory/product contact details for personalization).
Mitigations required (DPDP Act 2023): explicit consent, purpose limitation, minimization, retention limit + delete-on-request, no storage of consumer sensitive PII beyond need, session-only default for test reports. To be detailed in build; risk logged in decisions.md.

## 10. Evaluation gate (ship-blocker)
- 50+ gold queries (product→IS, scheme, hallmarking, labs) with expected IS/scheme/source.
- Metrics: groundedness (claim supported by citation), citation precision, correct refusal when unsure, scheme accuracy. Bar: >90% to ship.
- Glossary check: industry terms explained in plain EN/Hindi without loss of normative meaning.

## 11. Never-infer list (hard refuse + redirect to BIS)
- Product is certified / compliant / will get licence
- Verbatim full clause text not on authorized page
- Licence approval odds / timelines as guarantee
- Lab results / accreditation not listed on BIS source
- Legal interpretation as binding advice

## 12. Out of scope (MVP)
Full-text IS reader, auto-filling BIS licence forms, lab booking/payments, 22-language coverage, offline mode.
