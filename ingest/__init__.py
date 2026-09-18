"""Allowlist enforcement shared by crawler and retriever (decisions #2, #3)."""
from __future__ import annotations
import re

ALLOWED_HOSTS = ("bis.gov.in", "crsbis.in", "manakonline.in",
                 "lims.bis.gov.in", "standardsbis.bsbedge.com")


def host_of(url: str) -> str:
    return re.sub(r"^https?://", "", url).split("/")[0].lower()


def assert_allowlisted(url: str) -> str:
    if not any(h in host_of(url) for h in ALLOWED_HOSTS):
        raise ValueError(f"Blocked non-allowlisted source: {url}")
    return url
