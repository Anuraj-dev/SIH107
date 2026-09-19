"""Hostname allowlist for citations and live fetches (suffix-safe, no userinfo)."""
from __future__ import annotations

import urllib.parse
import urllib.request

ALLOWED_HOSTS = (
    "bis.gov.in",
    "crsbis.in",
    "manakonline.in",
    "lims.bis.gov.in",
    "standardsbis.bsbedge.com",
    "services.bis.gov.in",
    "standards.bis.gov.in",
    "www.crsbis.in",
)

# Crawlable for automated fetching. standardsbis.bsbedge.com is allowlisted
# for *linking* (e-sale citations) but BLOCKED for crawling by its
# robots.txt (`Disallow: /` for all bots — VERIFIED 2026-09-18, P1).
# manakonline.in is login-gated (P2) — no anonymous fetch.
BLOCKED_CRAWL_HOSTS = ("standardsbis.bsbedge.com", "manakonline.in")

KYS_PORTAL = "https://www.bis.gov.in/know-your-standard"


def host_of(url: str) -> str:
    """Parsed hostname only (no userinfo, no port, no trailing dot)."""
    host = urllib.parse.urlparse((url or "").strip()).hostname or ""
    return host.lower().rstrip(".")


def _has_userinfo(url: str) -> bool:
    p = urllib.parse.urlparse((url or "").strip())
    return p.username is not None or p.password is not None


def hostname_allowed(host: str, allowed: tuple[str, ...] = ALLOWED_HOSTS) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    for h in allowed:
        h = h.lower().rstrip(".")
        if host == h or host.endswith("." + h):
            return True
    return False


def assert_allowlisted(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Blocked non-allowlisted source: (empty)")
    p = urllib.parse.urlparse(raw)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"Blocked non-allowlisted source: {url}")
    if _has_userinfo(raw):
        raise ValueError(f"Blocked non-allowlisted source: {url}")
    if not hostname_allowed(p.hostname or ""):
        raise ValueError(f"Blocked non-allowlisted source: {url}")
    return url


def assert_crawlable(url: str) -> str:
    """Allowlist + robots/ToS gate: raises for e-sale (P1) and manakonline (P2)."""
    assert_allowlisted(url)
    if hostname_allowed(host_of(url), BLOCKED_CRAWL_HOSTS):
        raise ValueError(f"Crawl blocked by robots/ToS (manual/permissioned only): {url}")
    return url


def safe_public_url(url: str | None, fallback: str = KYS_PORTAL) -> str:
    """Citation/link URL, or Know-Your-Standard if the row is not allowlisted."""
    try:
        if url:
            return assert_allowlisted(url)
    except ValueError:
        pass
    return fallback


def _redirect_handler(crawl: bool = False):
    class AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            assert_allowlisted(newurl)
            if crawl:
                assert_crawlable(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return AllowlistRedirectHandler()


def allowlisted_opener(*handlers, crawl: bool = False):
    """urllib opener that re-allowlists every redirect hop."""
    return urllib.request.build_opener(_redirect_handler(crawl), *handlers)
