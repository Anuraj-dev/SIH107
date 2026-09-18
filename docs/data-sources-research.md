# BIS Data Sources — Primary-Source Research
_Date: 2026-09-18 (all fetches accessed this date) | Scope: is the data problem solved, and where can complete data come from?_

> Convention: every factual claim cites the first-party page/API/section actually observed, with URL + access date.
> Labels: **[VERIFIED]** = fetched live from the owning primary source on 2026-09-18 ·
> **[PARTIAL]** = page exists/link confirmed on primary source, body not extracted ·
> **[BLOCKED]** = could not verify (paywall/login/JS/403).

## 0. Verdict

**NO — the data problem is not solved.** The KB holds **16 standards rows (15 real + 1 withdrawn demo), 4 schemes, 5 labs, 6 glossary terms**
(`data/*.json`, counted 2026-09-18; matches `docs/implementation-plan.md` §0), while BIS's own publications put the live universe at
**≈23,823 Indian Standards** ([VERIFIED] BIS August 2025 newsletter, bis.gov.in PDF) and **22,471 department-wise**
([VERIFIED] DG-dashboard Published Standards page). Current standards coverage is **≈0.07%** of the universe. The good news:
all *metadata* fields the product needs (IS number/title/year/status/scope/committee, scheme pages, QCO flags, lab directory)
are published on BIS-owned portals — but they are fragmented across **~6 hosts**, partly JS-gated, and full text stays behind
login/paywall by design (decisions #2/#3 hold). Close the gap with a staged allowlist crawl (P0→P2 below), not broad scraping.

## 1. Coverage gap (numbers)

| Slice | BIS universe (primary source) | KB today | Gap |
|---|---|---|---|
| All Indian Standards | **23,823** ([VERIFIED] https://www.bis.gov.in/wp-content/uploads/2025/08/BIS-August-Newsletter-.pdf — "To date, it has released 23,823 Indian Standards", 2026-09-18; "more than 23,000" corroborated in https://www.bis.gov.in/wp-content/uploads/2025/04/BIS-NEWSLETTER-APRIL-2025.pdf) · Dept-wise total **22,471** (12,679 new + 9,792 revised, 17 depts; [VERIFIED] https://www.services.bis.gov.in/php/BIS_2.0/dgdashboard/Published_Standards, 2026-09-18; delta vs newsletter likely = different cut/dedup — treat 22.5–23.8k as the band) | 16 (15 real + IS 0000-DEMO) | **≈99.93% missing** |
| CRS products (Scheme-II) | **73 product rows**, each with IS number + QCO implementation date ([VERIFIED] https://www.crsbis.in/BIS/products-bis.do, 2026-09-18) | ~2 (IS 13252, IS 616 family implied) | high-value subset obtainable in one page |
| Compulsory-certification Schemes I/II/IV/X | Scheme list + Guidance Document on QCOs + Upcoming-QCOs page ([VERIFIED] https://www.bis.gov.in/product-certification/products-under-compulsory-certification/?lang=en, last-updated 2026-04-15 per page, 2026-09-18) | 4 scheme rows | QCO↔IS mapping not yet in KB |
| Lab directory | IS-wise test-facility search: lab name, OSL code, IS no/part/section/year, product/grade, charges, validity ([VERIFIED] form fields at https://lims.bis.gov.in/home/search_is_number/, 2026-09-18) + BIS-lab / recognised / empanelled endpoints | 5 unverified samples | 0 verified rows |
| e-sale catalogue metadata | Per-record: IS no, year, reaffirmed year, title, technical committee, status, amendment count; download behind login ([VERIFIED] sample IS 4326:2013 at https://standardsbis.bsbedge.com/BIS_SearchStandard.aspx?Standard_Number=IS%204326&id=535, 2026-09-18) | esale_base URL only | metadata harvestable within ToS limits (see §4) |

## 2. Per-source findings

### 2.1 Know-Your-Standard (KYS) app — P0 core
- Owner: BIS (ITSD). Entry page https://www.bis.gov.in/know-your-standard/?lang=en ([VERIFIED] 2026-09-18).
- What it offers (page body, [VERIFIED]): *"The 'Know Your Standard' feature provides a one-stop access to all the documents and data related to a selected
  Standard. The Standard can be searched by entering the IS Number or a Keyword (like Product name)… User can access … the PDF of the IS itself,
  amendments, gazette notifications, scheme of testing and inspections [STI] … list of licenses, list of laboratories testing for concerned IS,
  classification details and composition of the committee"* — via **[Explore → https://standards.bis.gov.in/website/know-your-standards]**.
- Fields obtainable as metadata: IS no, title, year, status, scope/keyword, committee, amendments, licence/lab lists. Full-text PDF links exist but stay behind access control — link out, never mirror (decisions #2/#3).
- Technical catch: `standards.bis.gov.in` is an **Angular SPA with no server-rendered content** ([VERIFIED] HTML shell `<app-root>` + JS bundles + devtools-blocking script, 2026-09-18).
  Ingestion = headless-browser crawl or reverse-engineered internal API; no public API docs found. Related crawlable routes on same app:
  `/website/published-standards/department-wise`, `/website/technical-departments/department-list`, `/website/wc-drafts`,
  `/website/review-of-standards` (route list [VERIFIED] in bis.gov.in nav, 2026-09-18).
- Next step: spike a Playwright fetch of one KYS record; record XHR endpoints; store raw snapshots per `implementation-plan.md` §3.

### 2.2 DG-dashboard Published Standards (eBIS) — P0 core, most crawlable
- Owner: BIS. URL https://www.services.bis.gov.in/php/BIS_2.0/dgdashboard/Published_Standards ([VERIFIED] 2026-09-18).
- Server-rendered tables: 17 technical departments (AYD 199, CED 1904, CHD 1986, EED 126, ETD 1848, FAD 2201, LITD 1512, MED 1359,
  MHD 1648, MSD 518, MTD 1639, PCD 1506, PGD 2529, SSD 164, TED 1346, TXD 1523, WRD 463; total **22,471**), each with
  new/revised/total list links; filters by aspect (Product Spec, Code of Practice, Methods of test, Terminology, Dimensions,
  System/Safety/Service specs, Indigenous vs adopted) and publication date. Notes *"standards published after 01 Oct 2025 are
  available in [the] new portal"* → post-Oct-2025 delta lives only on `standards.bis.gov.in`.
- Also links: KYS record view (`…/bisconnect/knowyourstandards/indian_standards/isdetails`), group-wise and ministry-wise classifications.
- Auth/rate: no login observed for listing pages; no robots.txt checked on this host — confirm before crawling; keep `crawl_delay_s: 2.0` (`config.yaml`).
- Next step: crawl dept totals → per-dept lists → per-standard rows (number/title/year/status); diff weekly.

### 2.3 CRS portal (crsbis.in) — P0 for compulsory flags
- Owner: BIS. About page https://www.crsbis.in/BIS/about-crs.do ([VERIFIED] 2026-09-18): CRS runs per **Scheme-II of Schedule-II of
  BIS (Conformity Assessment) Regulations, 2018**; phases notified by MeitY (2012: 15 + 15 categories; 2017: 13; 2020: 12 + 7),
  MNRE (solar PV, 2017), Chemicals & Fertilizers, Textiles — each with gazette-PDF links on the page.
- Product table https://www.crsbis.in/BIS/products-bis.do ([VERIFIED] 73 rows, 2026-09-18): product → IS number(s) → QCO date
  (e.g. IS 616:2017, IS 13252(Part 1):2010, IS 10322 series, IS 16046, IS 16102, IS 16242, IS 14286 PV series, IS 18112:2025 for TVs).
- Adjacent endpoints (existence [VERIFIED] via site nav, bodies not extracted): registration process, fee PDF, forms, FAQ,
  registered manufacturers (`/BIS/Lims_registrationc.do?hmode=getLimsData`), BIS recognised labs (`/BIS/bis_lab.do`), circulars.
- robots.txt: **none (404)** ([VERIFIED] https://www.crsbis.in/robots.txt, 2026-09-18) — still respect ToS + crawl-delay; static HTML, easy parse.
- Next step: ingest the 73-row table as the seed QCO/compulsory map (human-review `qco_status` per plan §2, never auto-assert).

### 2.4 LIMS lab directory (lims.bis.gov.in) — P0 for testing/lab answers
- Owner: BIS. IS search https://lims.bis.gov.in/home/search_is_number/ ([VERIFIED] form fields: lab name, IS no/part/section/year,
  title/product; result columns: lab, OSL code, IS no, product, grade/type/size, charges, validity, remark; 2026-09-18).
  GET returns empty result set — **query requires form POST/JS** ([VERIFIED]). Sibling endpoints (linked from bis.gov.in lab pages,
  [VERIFIED] https://www.bis.gov.in/laboratorys/testing-facility-and-testing-charges/?lang=en): `/home/bis_labs/`, `/home/labs/`,
  `/home/empaneled_labs/`. Static Group-1/Group-2 lab-list PDFs at `bis.gov.in/wp-content/uploads/2026/06/Group_1_24062026.pdf` and
  `…/2026/04/Group-2_23042026.pdf` ([PARTIAL] links verified, PDFs not fetched).
- robots.txt: no usable file (host returns app 404 page) ([VERIFIED] 2026-09-18) — treat as unpermissioned; gentle, attributed crawling only.
- Next step: POST a known IS (e.g. IS 10500) via test script; confirm result HTML; map to `labs` table; keep `unverified` flag until confirmed.

### 2.5 e-sale catalogue (standardsbis.bsbedge.com, BSB Edge) — P1 metadata, ToS-constrained
- Owner: BIS catalogue operated by BSB Edge (page footer: *"BSB Edge is Official Distributers…"*, [VERIFIED] 2026-09-18).
- Public without registration: search by **number/title + Advanced (Scope, Module, publication date)**; *"search for standards"* needs no account
  ([VERIFIED] https://standardsbis.bsbedge.com/BIS_FAQ.aspx?id=faq Q3–Q6, 2026-09-18). Record page shows number/year/**reaffirmed year**/title/
  **technical committee/status/amendment count** ([VERIFIED] §1 sample). **"Indigenous Indian Standards can be downloaded free of cost"**
  ([VERIFIED] homepage banner, 2026-09-18); free amendments after login; purchases/downloads need registered account (Q2, Q6–Q7).
- **Hard constraint: `robots.txt` = `User-agent: * / Disallow: /`** — entire site disallowed to bots ([VERIFIED] https://standardsbis.bsbedge.com/robots.txt, 2026-09-18).
  → No unattended crawling. Use manual snapshots / advance-search sparingly / contact BIS-ITSD or BSB Edge for a metadata feed; out-of-band
  "Download Search Result in Pdf/Excel" buttons exist on result pages ([VERIFIED] sample page) — human-driven export is the compliant path.
- Next step: keep `esale_url` per standard as link-out (already in schema); do NOT add e-sale to crawler allowlist until written permission.

### 2.6 Scheme / QCO / FMCS / Hallmarking / Manakonline pages — P0–P1 journeys
- Compulsory-certification hub https://www.bis.gov.in/product-certification/products-under-compulsory-certification/?lang=en ([VERIFIED] body, 2026-09-18):
  scheme *"basically voluntary"*; Central Govt mandates Standard Mark via **QCOs**; links to **Scheme-I / II / IV / X** sub-pages,
  **Guidance Document on QCOs** (PDF), **Upcoming QCOs – Notified and Due**, and **Indigenous IS – Free Download**; page last-updated 2026-04-15.
- FMCS overview, products-under-FMCS, hallmarking overview, jewellers registration, AHC lists (`huid.manakonline.in/MANAK/AHCListForWebsite`),
  training programmes/calendars, product-certification process/fee/FAQ: **existence + URL structure [VERIFIED] via bis.gov.in nav** (2026-09-18);
  article bodies not extracted (nav-heavy WP pages) → **[PARTIAL]**; re-fetch individually at ingest time.
- Manakonline https://www.manakonline.in/ ([VERIFIED] 2026-09-18): **login-gated service hub** (eBIS standardisation, Manakonline conformity
  assessment, CRS, FMCS, MSCD, LIMS, HUID hallmarking, training). No public licence/QCO search without login → **[BLOCKED]** for crawler;
  licence-lookup needs a BIS account or human-in-loop. robots.txt: none (404) ([VERIFIED] 2026-09-18).
- QCO gazette source: ministry QCO PDFs are linked from CRS/BIS pages ([VERIFIED] §2.3); a standing e-Gazette watch (egazette.nic.in) was **not**
  verified in this pass — open question, do not cite as source yet.

### 2.7 Crawl-permission snapshot (robots.txt, 2026-09-18)

| Host | robots.txt | Meaning for `ingest/` |
|---|---|---|
| `www.bis.gov.in` | Only `Disallow: /wp-admin/` (+ sitemaps) ([VERIFIED] https://www.bis.gov.in/robots.txt) | Polite crawl of public pages OK with delay + UA |
| `standardsbis.bsbedge.com` | `Disallow: /` for all bots ([VERIFIED]) | **Do not crawl**; manual/permissioned only |
| `crsbis.in` | 404, none ([VERIFIED]) | No prohibition, but no permission either — gentle + ToS-respecting |
| `lims.bis.gov.in` | No usable file (app 404) ([VERIFIED]) | Same as above |
| `manakonline.in` | 404, none ([VERIFIED]) | Moot — login-gated |
| `standards.bis.gov.in` | Not checked (SPA) | Check before automating; API use needs BIS confirmation |

## 3. Copyright / red-line box (decisions #2/#3 — unchanged)

- **DO NOT**: mirror full IS text; bulk-reproduce paid content; scrape third-party IS PDF copies; crawl e-sale (`Disallow: /`);
  auto-scrape login-gated Manakonline content; auto-assert QCO/compulsory status without human review.
- **DO**: ingest *metadata only* (number/year/title/scope/status/committee/amendments/QCO refs/lab listings/scheme procedures/FAQs);
  cite `IS + year + status + section + URL + last-checked`; link full text to e-sale/KYS; keep `source_snippet` to the fair snippet
  shown on the authorized page (`docs/product-brief.md` §4, `docs/decisions.md` #2–#4).
- Note: a *"Copyright [of] Indian Standards"* page is linked from BIS Consumer Engagement menus (`bis.gov.in/PDF/lab/copyright.pdf`,
  link existence [VERIFIED] 2026-09-18) but the PDF itself returned **403** ([BLOCKED]) — full ToS text still unconfirmed; re-check via
  BIS contact before Phase-1 live crawl. e-sale's paid-publication model (FAQ Q1–Q2, [VERIFIED]) independently confirms full text is commercial.

## 4. Recommended ingestion priority

- **P0 (unblocks pilot breadth)**: ① DG-dashboard dept lists → per-standard metadata (number/title/year/status) — §2.2;
  ② KYS-app records for scope/committee/amendments/licence-lab lists — §2.1; ③ CRS 73-row product→IS→QCO table as reviewed compulsory seed — §2.3;
  ④ LIMS IS-wise lab mapping for top-traffic IS — §2.4. Target: all compulsory-certification IS (~73 CRS + Scheme-I/FMCS lists) + top-500 by MSME demand before long tail.
- **P1 (depth/currency)**: e-sale metadata *via permissioned/manual exports only* (reaffirmed-year, amendment counts) — §2.5;
  FMCS/hallmarking/training/FAQ journey pages; Scheme-I/IV/X product lists; Upcoming-QCOs watch; supersession/withdrawal diff feed.
- **P2 (gated)**: Manakonline licence lookup (needs account), HUID AHC live lists, e-Gazette QCO automation, Hindi title/scope backfill, BIS metadata API/feed request.

## 5. Open questions (need BIS/human confirmation)

1. Is there an official metadata API/feed for `standards.bis.gov.in` (KYS + published-standards), and may the assistant poll it weekly? (Owner: BIS-ITSD.)
2. May the allowlist crawler fetch e-sale *metadata* despite `Disallow: /`, or is there a catalogue dump? (Owners: BIS + BSB Edge.)
3. Authoritative per-IS QCO/compulsory mapping file — does BIS publish one, or is the CRS table + Scheme pages + Guidance-on-QCOs the canonical set?
4. Are Hindi titles/scopes officially published anywhere, or must `title_hi`/`scope_hi` remain curated translations? (Affects `standards` table.)
5. Manakonline licence-search access for verification workflows — available to the project, or human-only?
6. Reconcile 23,823 (newsletter) vs 22,471 (dashboard) vs "19,000+" (e-sale FAQ) — confirm counting rules (withdrawn/adopted/dual-numbering) for the coverage denominator.
