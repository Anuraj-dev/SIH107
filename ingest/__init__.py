"""Allowlist enforcement shared by crawler and retriever (decisions #2, #3)."""
from __future__ import annotations
import re

ALLOWED_HOSTS = ("bis.gov.in", "crsbis.in", "manakonline.in",
                 "lims.bis.gov.in", "standardsbis.bsbedge.com",
                 "services.bis.gov.in", "standards.bis.gov.in",
                 "www.crsbis.in")

# Crawlable for automated fetching. standardsbis.bsbedge.com is allowlisted
# for *linking* (e-sale citations) but BLOCKED for crawling by its
# robots.txt (`Disallow: /` for all bots — VERIFIED 2026-09-18, P1).
# manakonline.in is login-gated (P2) — no anonymous fetch.
BLOCKED_CRAWL_HOSTS = ("standardsbis.bsbedge.com", "manakonline.in")


def host_of(url: str) -> str:
    return re.sub(r"^https?://", "", url).split("/")[0].lower()


def assert_allowlisted(url: str) -> str:
    if not any(h in host_of(url) for h in ALLOWED_HOSTS):
        raise ValueError(f"Blocked non-allowlisted source: {url}")
    return url


def assert_crawlable(url: str) -> str:
    """Allowlist + robots/ToS gate: raises for e-sale (P1) and manakonline (P2)."""
    assert_allowlisted(url)
    if any(h in host_of(url) for h in BLOCKED_CRAWL_HOSTS):
        raise ValueError(f"Crawl blocked by robots/ToS (manual/permissioned only): {url}")
    return url
