# BIS data sources — research (metadata only, decisions #2/#3)

_Date: 2026-09-18 (all claims re-verified live on this date unless noted)_
_Status: P0 breadth pipeline implemented in `ingest/breadth.py` + `scripts/breadth_crawl.py`_

> Constraint (decisions #2/#3, non-negotiable): **metadata only**
> (IS number / year / title / scope shown on the page / committee / status /
> amendments / QCO date / lab directory rows). Full standard text stays behind
> BIS e-sale / login — **never mirror PDFs, never paste verbatim clauses**.
> Crawler enforces the host allowlist in code (`ingest/__init__.py`) and
> refuses `standardsbis.bsbedge.com` (robots `Disallow: /`).

Coverage target: ~22,471–23,823 live Indian Standards on BIS's own portals
vs 16 curated rows in `data/*.json` (≈0.07%). The gap is closed in two tiers:

- **Breadth (this file + pipeline):** list-level metadata for all ~22,471
  standards from the DG dashboard (one session-cookie DataTables feed per
  department, ~65 requests total). No per-IS fetch needed for breadth.
- **Depth (existing curated KB):** full scope/keywords/slots stay hand-curated
  for the 15 high-traffic standards; per-IS detail enrichment is on-demand
  via `isdetails_mnd/<id>` (Basic Details card) — never bulk-fetched.

## P0 — crawlable breadth (VERIFIED 2026-09-18)

### 1. DG-dashboard Published Standards — VERIFIED

- URL: `https://www.services.bis.gov.in/php/BIS_2.0/dgdashboard/Published_Standards`
  (server-rendered department table; per-department lists at
  `.../dgdashboard/Published_Standards_new/totalpublishedstandardslist?depid=…&depname=…`).
- VERIFIED 2026-09-18: main page renders 17 departments totalling **22,471**
  (new + revised): AYD 199, CED 1904, CHD 1986, EED 126, ETD 1848, FAD 2201,
  LITD 1512, MED 1359, MHD 1648, MSD 518, MTD 1639, PCD 1506, PGD 2529,
  SSD 164, TED 1346, TXD 1523, WRD 463.
- VERIFIED 2026-09-18: per-department list is a session-cookie DataTables
  `serverSide` POST (`draw/start/length/search`) returning JSON
  `{recordsTotal, recordsFiltered, data[]}` — no login, cookie obtained by one
  GET on the main page. Sampled CED page 1: `IS 1121 (Part 1):2023`,
  `IS/ISO 6182-7:2004`, with columns IS Number | Title | Aspect |
  Degree of Equivalence | Date of Pub. | detail link `isdetails_mnd/<id>`.
- robots: `https://www.services.bis.gov.in/robots.txt` → 404 (no file,
  VERIFIED 2026-09-18) — crawl allowed with politeness (`crawl_delay_s: 2.0`,
  session reuse, DataTables page size ≤500).
- Most crawlable breadth source. Parser: `ingest/breadth.py:parse_dgdept_table`
  + `parse_dg_list_ajax`; crawler: `DGCrawler`.

### 2. Know-Your-Standard app — VERIFIED (list API via bisconnect; SPA needs spike for new portal)

- Legacy search/detail (server-rendered, crawlable):
  `https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/knowyourstandards/Indian_standards/isdetails/`
  with per-IS pages `isdetails_mnd/<id>`. VERIFIED 2026-09-18: detail page
  exposes a **Basic Details card** (IS Number + Hindi label, Title,
  Superseding IS, Degree of Equivalence, Revisions, Amendments, Aspect,
  Language, Reaffirmation year, Technical Department, Technical Committee,
  Member Secretary) plus Group/Sub-Group, cross-referenced IS/ISO lists,
  licence/lab/amendment/QCO AJAX tabs. Parser: `parse_kys_detail`.
- Public portal `https://www.bis.gov.in/know-your-standard` → VERIFIED
  2026-09-18 (200, WordPress page linking into search above).
- New Angular portal `https://standards.bis.gov.in/website/know-your-standards`
  → VERIFIED 2026-09-18 (200, SPA shell; data via `standardsadmin.bis.gov.in`
  microservices). robots `Allow: /` except login/admin/survey paths
  (VERIFIED 2026-09-18) — crawlable where server-rendered, but list payloads
  need a Playwright/API spike: **PARTIAL**, see §5 Q1.
- Post-01-Oct-2025 standards live on the new portal only (banner on both old
  pages, VERIFIED 2026-09-18) — DG-dashboard totals + new-portal spike must be
  combined for the ~23,823 upper bound.

### 3. CRS product table — VERIFIED

- URL (note `www.` — bare `crsbis.in` fails TLS hostname verification):
  `https://www.crsbis.in/BIS/products-bis.do` — VERIFIED 2026-09-18 (200,
  single static HTML table).
- Content: Sl.No. | Product | IS number | QCO implementation date.
  Sampled rows: amplifiers → `IS 616:2017`, laptops → `IS 13252(Part 1):2010`,
  self-ballasted LED lamps → `IS 16102(Part 1):2012`, CCTV → `IS 13252(Part 1):2010`.
- No `robots.txt` (404, VERIFIED 2026-09-18). Single-page seed for compulsory
  (QCO) flags — but QCO values still require human review before any
  compulsory claim (plan §2, §12). Parser: `parse_crs_table`.

### P0 labs — VERIFIED (on-demand, not bulk)

- URL: `https://lims.bis.gov.in/home/search_is_number/` — VERIFIED 2026-09-18
  (200). Filter form is a plain **GET** (`is_number__doc_no`, `part`,
  `section`, `year`, lab name, title/product).
- VERIFIED 2026-09-18 with `?is_number__doc_no=694`: server-rendered result
  rows — Lab Name, OSL code, IS No., Product, Grade/Type/Size, Testing Charges
  (excl. taxes), Facility Type, Effective/Validity dates (e.g. NTH Guwahati,
  OSL 5169204, IS 694 (2010), ₹20,000).
- `robots.txt` returns the LIMS HTML shell instead of rules (VERIFIED
  2026-09-18) — treated as no-disallow; still polite on-demand use only
  (per-IS lookup when a user asks, never a bulk scrape of charges tables).
  Helper: `lims_search_url` + `parse_lims_rows`.

## P1 — ToS-constrained: e-sale catalogue (BLOCKED for crawling)

- URL: `https://standardsbis.bsbedge.com/` — VERIFIED 2026-09-18 (200).
- `robots.txt` → `User-agent: * / Disallow: /` for **all bots** (VERIFIED
  2026-09-18). Record pages show number/year/reaffirmed/committee/status/
  amendments, but **do not crawl** — manual export / permissioned feed only.
- Crawler enforces this: `ingest.assert_crawlable` raises on this host even
  though it is allowlisted for *linking* (citations/e-sale URLs).
- `docs/decisions.md` #2 already forbids mirroring paid full text; e-sale
  stays a link-out (`esale_url`) only.

## P2 — gated: manakonline.in (BLOCKED for anonymous crawl)

- URL: `https://www.manakonline.in/` — login hub, no public search
  (PARTIAL: landing reachable, catalogue behind auth — VERIFIED 2026-09-18
  via banner/links on BIS pages; no anonymous record access found).
- QCO gazettes, HUID/AHC lists, Hindi titles need BIS/human confirmation —
  open questions in §5.

## §5 — open questions (need BIS/human confirmation)

1. New-portal (`standards.bis.gov.in`) list/search JSON contract — needs a
   Playwright/API spike; old DG-dashboard covers pre-Oct-2025 records.
2. QCO/compulsory effective dates per IS beyond the 73-row CRS table
   (gazette source of truth; CRS dates are the seed, reviewer confirms).
3. Hindi titles/scopes — detail pages carry Hindi *labels* with English
   values; noBulk Hindi corpus found; Hindi answers remain translations.
4. HUID/AHC directory bulk source — currently journey links only.
5. LIMS validity semantics — `Validity Date` blank on sampled rows; confirm
   meaning with BIS lab staff before surfacing.
6. Reaffirmation/supersession feed — detail pages show counts; a push
   notification source (BIS notifications page) needs reviewer wiring for
   the weekly refresh trigger.

## Refresh & review wiring

- Weekly `scripts/breadth_crawl.py` (dept lists + CRS) → raw snapshots →
  `pending_diffs` (`added` for new IS, `changed` on year/title/status drift)
  → batch review (`ingest.review approve-all` with distinct
  publisher/approver) → publish. Rollback: previous `kb/bis.db` snapshot
  restore per `docs/runbook.md` §KB restore.
- Per-IS detail enrichment is on-demand only (Basic Details card when a user
  or reviewer opens an IS), never a 22k-page bulk fetch.
- Coverage metric: `scripts/breadth_crawl.py --report` prints
  published / queued / live-total (≈22,471) so the 0.07% figure can never
  silently regress again.
