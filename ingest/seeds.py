"""Crawl seeds. Live fetch is OFF until human review (config ingest.live_crawl_enabled)."""
from __future__ import annotations

SEEDS = [
    ("know-your-standard", "https://www.bis.gov.in/know-your-standard"),
    ("product-certification", "https://www.bis.gov.in/product-certification/product-certification-overview/"),
    ("crs", "https://www.crsbis.in/BIS/about-crs.do"),
    ("fmcs", "https://www.bis.gov.in/fmcs/fmcs-overview/"),
    ("hallmarking", "https://www.bis.gov.in/hallmarking-overview/"),
    ("lims", "https://lims.bis.gov.in/home/search_is_number/"),
    ("training", "https://www.bis.gov.in/training-2/training-programmes/"),
    ("esale", "https://standardsbis.bsbedge.com/"),
]
