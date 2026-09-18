# BIS data sources — research (metadata only, decisions #2/#3)

_Date: 2026-09-18 (all claims verified live on this date unless noted)_
_Status: P0 breadth pipeline implemented in `ingest/breadth.py` + `scripts/breadth_crawl.py`_
_Combines: background-agent research pass (PR #2: newsletter band, QCO hub,
e-sale sample, KYS routes, robots table) + implementation-pass live probes
(DG DataTables session feed, LIMS GET filter, CRS TLS note)._

> Constraint (decisions #2/#3, non-negotiable): **metadata only**
> (IS number / year / title / scope shown on the page / committee / status /
> amendments / QCO date / lab directory rows). Full standard text stays behind
> BIS e-sale / login — **never mirror PDFs, never paste verbatim clauses**.
> Crawler enforces the host allowlist in code (`ingest/__init__.py`) and
> refuses `standardsbis.bsbedge.com` (robots `Disallow: /`).

Coverage target: **22,471** department-wise ([VERIFIED] DG-dashboard Published
Standards page, 2026-09-18; 17 departments) to **23,823** ([VERIFIED] BIS
August 2025 newsletter PDF, "To date, it has released 23,823 Indian
Standards", via research pass; "more than 23,000" corroborated in the April
2025 newsletter) vs 16 curated rows in `data/*.json` (≈0.07%). Treat
22.5–23.8k as the band (different cut/dedup — open question §5 Q7). The gap
is closed in two tiers:

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
  (12,679 new + 9,792 revised per dashboard columns): AYD 199, CED 1904,
  CHD 1986, EED 126, ETD 1848, FAD 2201, LITD 1512, MED 1359, MHD 1648,
  MSD 518, MTD 1639, PCD 1506, PGD 2529, SSD 164, TED 1346, TXD 1523, WRD 463.
  Filters by aspect (Product Spec, Code of Practice, Methods of test,
  Terminology, Dimensions, System/Safety/Service specs) and publication date.
- VERIFIED 2026-09-18: per-department list is a session-cookie DataTables
  `serverSide` POST (`draw/start/length/search`) returning JSON
  `{recordsTotal, recordsFiltered, data[]}` — no login, cookie obtained by one
  GET on the main page. Sampled CED page 1: `IS 1121 (Part 1):2023`,
  `IS/ISO 6182-7:2004`, with columns IS Number | Title | Aspect |
  Degree of Equivalence | Date of Pub. | detail link `isdetails_mnd/<id>`.
  Pages cap below the requested length — the crawler advances by actual batch
  size with session refresh + retry.
- Post-Oct-2025 banner: standards published after 01 Oct 2025 live on the new
  portal only — dashboard + new-portal spike combine for the upper bound.
- robots: `https://www.services.bis.gov.in/robots.txt` → 404 (no file,
  VERIFIED 2026-09-18) — crawl allowed with politeness (`crawl_delay_s: 2.0`,
  session reuse, checkpoints in `kb/breadth_raw/`).
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
- KYS feature page (`bis.gov.in/know-your-standard`, VERIFIED 2026-09-18)
  describes one-stop access per standard (IS PDF, amendments, gazettes, STI,
  licence/lab lists, committee) via **Explore →
  `standards.bis.gov.in/website/know-your-standards`**; full-text links stay
  behind access control — link out, never mirror. Related crawlable routes on
  the new app: `/website/published-standards/department-wise`,
  `/website/technical-departments/department-list`, `/website/wc-drafts`,
  `/website/review-of-standards` (route list VERIFIED in bis.gov.in nav).
- New Angular portal `https://standards.bis.gov.in/website/know-your-standards`
  → VERIFIED 2026-09-18 (200, SPA shell; data via `standardsadmin.bis.gov.in`
  microservices). robots `Allow: /` except login/admin/survey paths
  (VERIFIED 2026-09-18) — crawlable where server-rendered, but list payloads
  need a Playwright/API spike: **PARTIAL**, see §5 Q1.

### 3. CRS product table — VERIFIED

- URL (note `www.` — bare `crsbis.in` fails TLS hostname verification):
  `https://www.crsbis.in/BIS/products-bis.do` — VERIFIED 2026-09-18 (200,
  single static HTML table, 73 rows).
- Content: Sl.No. | Product | IS number | QCO implementation date.
  Sampled rows: amplifiers → `IS 616:2017`, laptops → `IS 13252(Part 1):2010`,
  self-ballasted LED lamps → `IS 16102(Part 1):2012`, CCTV → `IS 13252(Part 1):2010`.
- CRS runs per Scheme-II of the BIS (Conformity Assessment) Regulations 2018;
  phases notified by MeitY/MNRE/others with gazette-PDF links on the about
  page (research pass). Adjacent endpoints (existence VERIFIED via site nav,
  bodies not extracted — PARTIAL): registration process, fee PDF, forms, FAQ,
  registered manufacturers, recognised labs, circulars.
- No `robots.txt` (404, VERIFIED 2026-09-18). Single-page seed for compulsory
  (QCO) flags — but QCO values still require human review before any
  compulsory claim (plan §2, §12). Parser: `parse_crs_table`.

### P0 labs — VERIFIED (on-demand, not bulk)

- URL: `https://lims.bis.gov.in/home/search_is_number/` — VERIFIED 2026-09-18
  (200). Filter form is a plain **GET** (`is_number__doc_no`, `part`,
  `section`, `year`, lab name, title/product) — correction to the research
  pass, which reported POST-only: a live probe with `?is_number__doc_no=694`
  returned server-rendered result rows (Lab Name, OSL code, IS No., Product,
  Grade/Type/Size, Testing Charges excl. taxes, Validity dates — e.g. NTH
  Guwahati, OSL 5169204, IS 694 (2010), ₹20,000).
- Sibling endpoints (linked from bis.gov.in lab pages, PARTIAL):
  `/home/bis_labs/`, `/home/labs/`, `/home/empaneled_labs/`; static Group-1 /
  Group-2 lab-list PDFs (links VERIFIED, PDFs not fetched).
- `robots.txt` returns the LIMS HTML shell instead of rules (VERIFIED
  2026-09-18) — treated as no-disallow; still polite on-demand use only
  (per-IS lookup when a user asks, never a bulk scrape of charges tables).
  Helper: `lims_search_url` + `parse_lims_rows`.

## P1 — ToS-constrained: e-sale catalogue (BLOCKED for crawling)

- URL: `https://standardsbis.bsbedge.com/` — VERIFIED 2026-09-18 (200).
- `robots.txt` → `User-agent: * / Disallow: /` for **all bots** (VERIFIED
  2026-09-18). Sample record `IS 4326:2013` shows number/year/reaffirmed/
  committee/status/amendments; homepage banner notes indigenous standards are
  free to download after login; result pages carry human-driven Pdf/Excel
  export buttons — the compliant path is **manual export / permissioned feed
  only, never unattended crawling**.
- Crawler enforces this: `ingest.assert_crawlable` raises on this host even
  though it is allowlisted for *linking* (citations/e-sale URLs).
- `docs/decisions.md` #2 already forbids mirroring paid full text; e-sale
  stays a link-out (`esale_url`) only.

## P2 — gated: manakonline.in (BLOCKED for anonymous crawl)

- URL: `https://www.manakonline.in/` — login hub (eBIS standardisation,
  conformity assessment, CRS, FMCS, MSCD, LIMS, HUID, training), no public
  search (PARTIAL: landing reachable; robots 404 VERIFIED 2026-09-18 via
  research pass; no anonymous record access found).
- QCO gazettes, HUID/AHC lists (`huid.manakonline.in/MANAK/AHCListForWebsite`
  existence VERIFIED via nav), Hindi titles need BIS/human confirmation —
  open questions in §5.

## Crawl-permission snapshot (robots.txt, 2026-09-18)

| Host | robots.txt | Meaning for `ingest/` |
|---|---|---|
| `www.bis.gov.in` | Only `Disallow: /wp-admin/` (+ sitemaps) | Polite crawl of public pages OK |
| `www.services.bis.gov.in` | 404, none | Polite crawl OK (session reuse + delay) |
| `standards.bis.gov.in` | `Allow: /` except login/admin/survey | Crawlable where server-rendered; API needs spike |
| `www.crsbis.in` | 404, none | Gentle, ToS-respecting static parse |
| `lims.bis.gov.in` | No usable file (app shell) | On-demand per-IS GET only |
| `standardsbis.bsbedge.com` | `Disallow: /` all bots | **Do not crawl** |
| `manakonline.in` | 404, none | Moot — login-gated |

## Copyright / red-line box (decisions #2/#3 — unchanged)

- **DO NOT**: mirror full IS text; bulk-reproduce paid content; scrape
  third-party IS PDF copies; crawl e-sale; auto-scrape login-gated
  Manakonline content; auto-assert QCO/compulsory status without human review.
- **DO**: ingest *metadata only*; cite `IS + year + status + section + URL +
  last-checked`; link full text to e-sale/KYS.
- Note: the BIS copyright PDF link (`bis.gov.in/PDF/lab/copyright.pdf`)
  returned **403** (BLOCKED — full ToS text unconfirmed); the e-sale paid
  model independently confirms full text is commercial. Re-check via BIS
  contact before any scope change.

## §5 — open questions (need BIS/human confirmation)

1. New-portal (`standards.bis.gov.in`) list/search JSON contract — needs a
   Playwright/API spike; old DG-dashboard covers pre-Oct-2025 records.
2. QCO/compulsory effective dates per IS beyond the 73-row CRS table
   (compulsory-certification hub: `bis.gov.in/product-certification/products-under-compulsory-certification/`
   with Scheme-I/II/IV/X pages, Guidance Document on QCOs, Upcoming-QCOs —
   last-updated 2026-04-15; gazette PDFs linked from CRS/BIS pages). A
   standing e-Gazette watch was **not** verified — do not cite yet.
3. Hindi titles/scopes — detail pages carry Hindi *labels* with English
   values; no bulk Hindi corpus found; Hindi answers remain translations.
4. HUID/AHC directory bulk source — currently journey links only.
5. LIMS validity semantics — `Validity Date` blank on sampled rows; confirm
   meaning with BIS lab staff before surfacing.
6. Reaffirmation/supersession feed — detail pages show counts; a push
   notification source needs reviewer wiring for the weekly refresh trigger.
7. Reconcile 23,823 (newsletter) vs 22,471 (dashboard) vs "19,000+" (e-sale
   FAQ) — confirm counting rules (withdrawn/adopted/dual-numbering) for the
   coverage denominator.

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
