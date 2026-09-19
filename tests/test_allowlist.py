"""Hostname allowlist: suffix-safe, no userinfo, no substring bypass."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bis_assistant.allowlist import (  # noqa: E402
    assert_allowlisted,
    assert_crawlable,
    host_of,
    safe_public_url,
)


OK = [
    "https://www.bis.gov.in/know-your-standard/",
    "https://bis.gov.in/x",
    "https://lims.bis.gov.in/home/",
    "https://www.services.bis.gov.in/php/BIS_2.0/",
    "https://www.crsbis.in/BIS/products-bis.do",
    "https://standardsbis.bsbedge.com/sale",
]


BAD = [
    "https://bis.gov.in.evil.example/x",
    "https://notbis.gov.in/x",
    "https://bis.gov.in@127.0.0.1/",
    "https://evilbis.gov.in.tk/",
    "https://not-bis.gov.in.attacker.test/a",
    "javascript:alert(1)",
    "",
    "https://example.com/x",
]


def test_allowlisted_official_hosts():
    for u in OK:
        assert assert_allowlisted(u) == u


def test_substring_and_userinfo_blocked():
    for u in BAD:
        with pytest.raises(ValueError):
            assert_allowlisted(u)


def test_host_of_strips_userinfo():
    assert host_of("https://bis.gov.in@127.0.0.1/x") == "127.0.0.1"
    assert host_of("https://www.bis.gov.in:443/x") == "www.bis.gov.in"


def test_safe_public_url_rewrites():
    assert safe_public_url("https://evil.example/phish").startswith("https://www.bis.gov.in")
    assert "bis.gov.in" in safe_public_url("https://www.bis.gov.in/x")


def test_generated_answer_sources_sanitize_untrusted_urls():
    from bis_assistant.rag_answer import build_sources, format_rag_citation

    evidence = [{"standard_number": "IS 1", "title": "t",
                 "chunk_text": "hello", "source_url": "https://evil.example/phish"}]
    source = build_sources(evidence)[0]
    citation = format_rag_citation(evidence[0])
    assert source["url"].startswith("https://www.bis.gov.in")
    assert "evil.example" not in citation


def test_redirect_hop_rechecks_allowlist():
    from bis_assistant.allowlist import _redirect_handler
    h = _redirect_handler()
    class Req:
        full_url = "https://www.bis.gov.in/"
    with pytest.raises(ValueError):
        h.redirect_request(Req(), None, 302, "Found", {}, "https://127.0.0.1/steal")


def test_crawlable_blocks_esale_and_manak():
    with pytest.raises(ValueError):
        assert_crawlable("https://standardsbis.bsbedge.com/")
    with pytest.raises(ValueError):
        assert_crawlable("https://www.manakonline.in/")
