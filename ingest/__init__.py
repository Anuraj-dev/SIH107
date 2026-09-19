"""Allowlist enforcement shared by crawler and retriever (decisions #2, #3)."""
from __future__ import annotations

import sys
from pathlib import Path

_src = Path(__file__).resolve().parents[1] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from bis_assistant.allowlist import (  # noqa: E402
    ALLOWED_HOSTS,
    BLOCKED_CRAWL_HOSTS,
    allowlisted_opener,
    assert_allowlisted,
    assert_crawlable,
    host_of,
    hostname_allowed,
    safe_public_url,
)

__all__ = (
    "ALLOWED_HOSTS",
    "BLOCKED_CRAWL_HOSTS",
    "allowlisted_opener",
    "assert_allowlisted",
    "assert_crawlable",
    "host_of",
    "hostname_allowed",
    "safe_public_url",
)
