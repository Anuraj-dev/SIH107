"""Crawl seeds. Live fetch is OFF until human review (config ingest.live_crawl_enabled).

Seed tiers per docs/data-sources-research.md (all VERIFIED 2026-09-18):
- P0 crawlable breadth: DG dashboard (dept totals + DataTables lists),
  KYS bisconnect search/detail, CRS products table (www. host — bare domain
  fails TLS), LIMS IS-wise search (on-demand GET).
- P1 BLOCKED: e-sale (robots Disallow: /) — link-out only, never crawl.
- P2 gated: manakonline.in — login hub, no anonymous fetch.
"""
from __future__ import annotations

SEEDS = [
    ("dg-dashboard", "https://www.services.bis.gov.in/php/BIS_2.0/dgdashboard/Published_Standards"),
    ("know-your-standard", "https://www.bis.gov.in/know-your-standard"),
    ("kys-search", "https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/knowyourstandards/Indian_standards/isdetails/"),
    ("kys-new-portal", "https://standards.bis.gov.in/website/know-your-standards"),
    ("crs-products", "https://www.crsbis.in/BIS/products-bis.do"),
    ("product-certification", "https://www.bis.gov.in/product-certification/product-certification-overview/"),
    ("crs", "https://www.crsbis.in/BIS/about-crs.do"),
    ("fmcs", "https://www.bis.gov.in/fmcs/fmcs-overview/"),
    ("hallmarking", "https://www.bis.gov.in/hallmarking-overview/"),
    ("lims", "https://lims.bis.gov.in/home/search_is_number/"),
    ("training", "https://www.bis.gov.in/training-2/training-programmes/"),
    # P1/P2 — documented, never crawled (assert_crawlable raises):
    ("esale-manual-only", "https://standardsbis.bsbedge.com/"),
    ("manakonline-gated", "https://www.manakonline.in/"),
]
