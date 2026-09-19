"""Breadth ingestion: lawful metadata-only crawlers for BIS's own portals.

Covers docs/data-sources-research.md P0 sources (all VERIFIED 2026-09-18):

- DG dashboard department totals + per-department DataTables JSON feeds
  (services.bis.gov.in — no robots.txt; session-cookie POST, polite delay).
- Know-Your-Standard bisconnect detail pages (isdetails_mnd/<id> Basic Details).
- CRS product table (www.crsbis.in — single static page; QCO seed only).
- LIMS IS-wise search (GET filter; on-demand per IS, never bulk).

Hard limits (decisions #2/#3): metadata only, never full-text PDFs;
standardsbis.bsbedge.com is BLOCKED by robots (assert_crawlable raises);
manakonline.in is gated (no anonymous fetch — helpers raise).

Stdlib only (urllib + http.cookiejar + re + json + time).
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import urllib.parse
import urllib.request

from . import allowlisted_opener, assert_allowlisted, assert_crawlable

DG_MAIN = ("https://www.services.bis.gov.in/php/BIS_2.0/"
           "dgdashboard/Published_Standards")
DG_LIST_TMPL = ("https://www.services.bis.gov.in/php/BIS_2.0/"
                "dgdashboard/Published_Standards_new/"
                "totalpublishedstandardslist"
                "?depid={depid}&depname={depname}&aspect=&doe=&dt_from=&dt_to=&t={total}")
KYS_SEARCH = ("https://www.services.bis.gov.in/php/BIS_2.0/"
              "bisconnect/knowyourstandards/Indian_standards/isdetails/")
KYS_DETAIL = ("https://www.services.bis.gov.in/php/BIS_2.0/"
              "bisconnect/knowyourstandards/Indian_standards/isdetails_mnd/{sid}")
CRS_PRODUCTS = "https://www.crsbis.in/BIS/products-bis.do"
LIMS_SEARCH = "https://lims.bis.gov.in/home/search_is_number/"

UA = {"User-Agent": "BIS-Assistant-KBbot/1.0 (metadata-only; +https://www.bis.gov.in/)"}

# ---------------------------------------------------------------------------
# IS number normalisation ("IS 1121 (Part 1):2023" -> canonical parts)


def normalize_is_number(raw: str) -> dict:
    """Split a DG-dashboard IS cell into is_number / year / part.

    Keeps the canonical short form used by the KB (e.g. "IS 1121",
    "IS 16102-1", "IS 13252") while preserving part/year separately so the
    citation renderer can show the full designation.
    """
    text = re.sub(r"\s+", " ", (_html.unescape(raw or "")).strip())
    year = ""
    m = re.search(r":\s*(\d{4})\s*$", text)
    if m:
        year, text = m.group(1), text[:m.start()].strip()
    part = ""
    m = re.search(r"\(\s*Part\s*([^)]*)\)", text, re.IGNORECASE)
    if m:
        part = re.sub(r"\s+", " ", m.group(1)).strip(" /")
        text = (text[:m.start()] + " " + text[m.end():]).strip()
    m = re.search(r"IS\s*[/-]?\s*(?:ISO\s*)?([\d]+(?:\s*-\s*\d+)?)",
                  text, re.IGNORECASE)
    if not m:
        return {"is_number": "", "year": year, "part": part,
                "designation": re.sub(r"\s+", " ", raw or "").strip()}
    num = re.sub(r"\s+", "", m.group(1))
    return {"is_number": f"IS {num}", "year": year, "part": part,
            "designation": re.sub(r"\s+", " ", raw or "").strip()}


def is_key(is_number: str) -> tuple[str, str]:
    """Normalised identity key: ("302", "1") for "IS 302-1" and
    "IS 302 (Part 1)" alike, ("10500", "") for "IS 10500"."""
    m = re.search(r"IS\s*([\d]+)", is_number or "", re.IGNORECASE)
    stem = m.group(1) if m else re.sub(r"\s+", " ", is_number or "").strip()
    sub = ""
    m = re.search(r"\(\s*Part\s*([^)]*)\)", is_number or "", re.IGNORECASE)
    if m:
        sub = re.sub(r"\s+", "", m.group(1))
    else:
        m = re.search(r"IS\s*[\d]+\s*-\s*([\d]+)", is_number or "", re.IGNORECASE)
        if m:
            sub = m.group(1)
    return (stem, sub)


def _clean_cell(cell_html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", cell_html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


def _cell_link(cell_html: str) -> str:
    m = re.search(r'href="([^"]+)"', cell_html or "")
    return _html.unescape(m.group(1)).replace("\\/", "/") if m else ""


# ---------------------------------------------------------------------------
# DG dashboard: department discovery


def parse_dgdept_table(main_html: str) -> list[dict]:
    """Extract [{depid, depname, dept, dept_code, total, list_url}]."""
    import base64
    out = []
    for m in re.finditer(
            r"totalpublishedstandardslist\?depid=([^&\"']+)&depname=([^&\"']+)"
            r"[^\"]*?t=(\d+)", main_html):
        depid = urllib.parse.unquote(m.group(1))
        depname = urllib.parse.unquote(m.group(2))
        try:
            code = base64.b64decode(depname + "==").decode("utf-8", "replace").strip()
        except Exception:
            code = depname
        # department label sits in the same <tr>: nearest preceding "... Department (XXX)" link
        row_start = main_html.rfind("<tr", 0, m.start())
        row = main_html[row_start:m.end()]
        dm = re.search(r"([A-Za-z /&.\-']+Department \([A-Z]+\))", row)
        label = re.sub(r"\s+", " ", dm.group(1)).strip() if dm else code
        rec = {"depid": m.group(1), "depname": m.group(2), "dept": label,
               "dept_code": code, "total": int(m.group(3)),
               "list_url": DG_LIST_TMPL.format(depid=m.group(1),
                                               depname=m.group(2),
                                               total=m.group(3))}
        if all(r["depid"] != rec["depid"] for r in out):
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# DG dashboard: DataTables list payloads


def parse_dg_list_ajax(payload: str | dict) -> list[dict]:
    """Parse one DataTables serverSide JSON page into KB-ready records.

    Each data[] row: [sno, IS-cell(html), title, aspect, equivalence,
    pub_date, action(html), view(html)]. Metadata only.
    """
    obj = json.loads(payload) if isinstance(payload, str) else payload
    records = []
    for row in obj.get("data", []) or []:
        if len(row) < 6:
            continue
        norm = normalize_is_number(_clean_cell(str(row[1])))
        if not norm["is_number"]:
            continue
        # Keep parts distinct: "IS 17424 (Part 1)" vs "IS 17424 (Part 2)".
        # Verifier/retriever match on the digits, so citations keep working.
        is_no = norm["is_number"]
        if norm["part"]:
            is_no = f"{is_no} (Part {norm['part']})"
        records.append({
            "is_number": is_no,
            "year": norm["year"],
            "part": norm["part"],
            "designation": norm["designation"],
            "title_en": _clean_cell(str(row[2] or "")),
            "aspect": _clean_cell(str(row[3] or "")),
            "equivalence": _clean_cell(str(row[4] or "")),
            "pub_date": _clean_cell(str(row[5] or "")),
            "detail_url": _cell_link(str(row[7] if len(row) > 7 else row[1])),
            "status": "Active",
        })
    return records


def to_kb_row(rec: dict, today: str) -> dict:
    """Map a breadth record onto the kb_store standards schema (v2 fields)."""
    scope = rec.get("title_en", "")
    designation = rec.get("designation") or rec["is_number"]
    return {
        "is_number": rec["is_number"],
        "year": rec.get("year", ""),
        "title_en": rec.get("title_en", "") or designation,
        "title_hi": "",
        "scope_en": scope or designation,
        "scope_hi": "",
        "status": rec.get("status", "Active"),
        "scheme_key": "",
        "scheme_text": "Confirm scheme/QCO on the BIS portal before manufacture.",
        "source_url": rec.get("detail_url") or KYS_SEARCH,
        "esale_url": "https://standardsbis.bsbedge.com/",
        "section_ref": "",
        "source_snippet": "List-level metadata from DG dashboard (%s); detail enrichment pending."
                          % (rec.get("dept", rec.get("department", "BIS"))),
        "qco_status": "unknown",
        "qco_checked_at": None,
        "keywords_json": "[]",
        "clarify_json": "[]",
        "captured_at": today,
        "last_checked": today,
        "supersedes": rec.get("supersedes", ""),
        "version": 1,
        "department": rec.get("dept", rec.get("department", "")),
        "dept_code": rec.get("dept_code", ""),
        "aspect": rec.get("aspect", ""),
        "equivalence": rec.get("equivalence", ""),
        "pub_date": rec.get("pub_date", ""),
        "detail_url": rec.get("detail_url", ""),
    }


# ---------------------------------------------------------------------------
# Know-Your-Standard detail pages (on-demand enrichment, never bulk)


def parse_kys_detail(detail_html: str) -> dict:
    """Extract the Basic Details card + group block from isdetails_mnd/<id>."""
    out: dict[str, str] = {}
    # Basic Details: sequence of qs-label / value-label pairs
    pairs = re.findall(
        r'<label[^>]*class="[^"]*\bqs\b[^"]*"[^>]*>(.*?)</label>\s*'
        r'<label[^>]*>\s*:\s*</label>\s*'
        r'<label[^>]*class="[^"]*\brly\b[^"]*"[^>]*>(.*?)</label>',
        detail_html, re.S | re.IGNORECASE)
    for raw_k, raw_v in pairs:
        key = re.sub(r"<[^>]+>", "", raw_k)
        key = re.sub(r"\s+", " ", _html.unescape(key)).split("/")[0].strip().lower()
        val = re.sub(r"<[^>]+>", " ", raw_v)
        out[key] = re.sub(r"\s+", " ", _html.unescape(val)).strip()
    # Group / Sub Group / Aspect rows use a th/td-ish table nearby
    for label in ("group", "sub group", "sub sub group", "aspect",
                  "certification", "short commom man's title"):
        m = re.search(re.escape(label) + r"\s*:\s*([^<|]{2,200})",
                      re.sub(r"<[^>]+>", "|", detail_html), re.IGNORECASE)
        if m and label not in out:
            out[label] = re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip(" |")
    norm = normalize_is_number(out.get("is number", ""))
    return {
        "is_number": norm["is_number"],
        "year": norm["year"] or "",
        "part": norm["part"],
        "title_en": out.get("is title", ""),
        "supersedes": "" if out.get("superseding is", "none").lower() == "none" else out.get("superseding is", ""),
        "equivalence": out.get("degree of equivalence", ""),
        "revisions": out.get("number of revisions", ""),
        "amendments": out.get("number of amendments", ""),
        "aspect": out.get("aspect", ""),
        "language": out.get("language", ""),
        "reaffirmation": out.get("reaffirmation year", ""),
        "department": out.get("technical department", ""),
        "committee": out.get("technical committee", ""),
        "secretary": out.get("member secretary", ""),
        "group": out.get("group", ""),
        "short_title": out.get("short commom man's title", ""),
    }


# ---------------------------------------------------------------------------
# CRS product table (single page; QCO seed)


def parse_crs_table(crs_html: str) -> list[dict]:
    """Parse the CRS products-bis.do table into [{product, is_raw, qco_date}]."""
    m = re.search(r"<table.*?</table>", crs_html, re.S | re.IGNORECASE)
    if not m:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S | re.IGNORECASE)
    out = []
    for r in rows[1:]:  # skip header
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.IGNORECASE)
        if len(cells) < 4:
            continue
        out.append({"product": _clean_cell(cells[1]),
                    "is_raw": _clean_cell(cells[2]),
                    "qco_date": _clean_cell(cells[3])})
    return out


def crs_is_numbers(is_raw: str) -> list[str]:
    """Split CRS IS cells ("IS 616 :2017 OR IS 616:2017 & IS 18112:2025")."""
    found = []
    for chunk in re.split(r"\bOR\b|&|;", is_raw or "", flags=re.IGNORECASE):
        n = normalize_is_number(chunk)
        if n["is_number"] and n["is_number"] not in found:
            found.append(n["is_number"])
    return found


# ---------------------------------------------------------------------------
# LIMS (on-demand GET filter; never bulk)


def lims_search_url(doc_no: str = "", part: str = "",
                    section: str = "", year: str = "") -> str:
    params = {"is_number__doc_no": doc_no, "is_number__part": part,
              "is_number__section": section, "is_number__year": year}
    return LIMS_SEARCH + "?" + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v})


def parse_lims_rows(lims_html: str, limit: int = 25) -> list[dict]:
    """Parse server-rendered LIMS result rows (lab directory metadata)."""
    lims_html = re.sub(r"<!--.*?-->", " ", lims_html, flags=re.S)  # commented-out cols
    tables = re.findall(r"<table.*?</table>", lims_html, re.S | re.IGNORECASE)
    best: list[str] = []
    for t in tables:
        if "Lab Name" in t and "Osl Code" in t:
            best = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S | re.IGNORECASE)[1:]
            break
    out = []
    for r in best[:limit]:
        # NOTE: live LIMS HTML is sloppy — <td> cells often close with </th>.
        cells = [_clean_cell(c) for c in
                 re.findall(r"<td[^>]*>(.*?)</t[dh]>", r, re.S | re.IGNORECASE)]
        if len(cells) < 6:
            continue
        charge_m = re.search(r"\d[\d,]*", cells[6] if len(cells) > 6 else "")
        out.append({"lab": cells[1] if len(cells) > 1 else "",
                    "osl": cells[2] if len(cells) > 2 else "",
                    "is_no": cells[3] if len(cells) > 3 else "",
                    "product": cells[4] if len(cells) > 4 else "",
                    "charges": charge_m.group(0) if charge_m else "",
                    "validity": cells[-2] if len(cells) > 8 else ""})
    return out


# ---------------------------------------------------------------------------
# Polite session crawler (DG dashboard needs cookie session for AJAX POSTs)


class DGCrawler:
    """Cookie-session client for the DG dashboard DataTables feeds."""

    def __init__(self, delay_s: float = 2.0, timeout_s: int = 45):
        import http.cookiejar
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        jar: http.cookiejar.CookieJar = http.cookiejar.CookieJar()
        self._opener = allowlisted_opener(
            urllib.request.HTTPCookieProcessor(jar), crawl=True)
        self._last = 0.0

    def refresh_session(self) -> None:
        """Re-GET the dashboard main page (fresh cookies after expiry)."""
        self.get(DG_MAIN)

    def _polite(self) -> None:
        wait = self.delay_s - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, url: str) -> str:
        assert_crawlable(url)
        self._polite()
        req = urllib.request.Request(url, headers=dict(UA))
        last: Exception | None = None
        for attempt in range(3):
            try:
                with self._opener.open(req, timeout=self.timeout_s) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:  # transient BIS TLS/read timeouts: retry
                last = e
                time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"GET failed after 3 attempts: {url} ({last!r})")

    def post_list_page(self, list_url: str, start: int,
                       length: int = 500) -> dict:
        """Fetch one DataTables page (serverSide POST, session cookie)."""
        assert_crawlable(list_url)
        self._polite()
        payload = urllib.parse.urlencode({
            "draw": "1", "start": str(start), "length": str(length),
            "search[value]": "", "search[regex]": "false",
        }).encode()
        req = urllib.request.Request(
            list_url, data=payload,
            headers={**UA, "X-Requested-With": "XMLHttpRequest",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "Referer": list_url})
        last: Exception | None = None
        for attempt in range(3):
            try:
                self._polite()
                with self._opener.open(req, timeout=self.timeout_s) as r:
                    ctype = r.headers.get_content_type()
                    body = r.read().decode("utf-8", "replace")
                break
            except Exception as e:
                last = e
                time.sleep(2.0 * (attempt + 1))
        else:
            raise RuntimeError(f"POST failed after 3 attempts: {list_url} ({last!r})")
        if ctype != "application/json" and '"data"' not in body:
            raise RuntimeError(f"unexpected list response ({ctype}) for {list_url}")
        return json.loads(body)

    def crawl_department(self, dept: dict, length: int = 500,
                         max_pages: int | None = None,
                         progress=None) -> list[dict]:
        """Paginate one department's totalpublishedstandardslist feed.

        Advances by the ACTUAL batch size (the server sometimes caps pages
        below the requested length) and stops on an empty page or when the
        server's recordsFiltered count is reached. Refreshes the cookie
        session once if POSTs fail persistently (BIS sessions expire).
        """
        assert_allowlisted(dept["list_url"])
        records: list[dict] = []
        start = 0
        expected: int | None = None
        pages = 0
        refreshed = False
        while True:
            if max_pages is not None and pages >= max_pages:
                break
            try:
                page = self.post_list_page(dept["list_url"], start, length)
            except RuntimeError:
                if refreshed:
                    raise
                refreshed = True
                self.refresh_session()
                continue
            refreshed = False
            if expected is None:
                expected = int(page.get("recordsFiltered")
                               or page.get("recordsTotal") or 0)
            batch = parse_dg_list_ajax(page)
            for rec in batch:
                rec.update(dept=dept["dept"], dept_code=dept.get("dept_code", ""),
                           depid=dept["depid"])
            records.extend(batch)
            pages += 1
            if progress:
                progress(dept.get("dept_code", "?"), len(records), expected or 0)
            if not batch or (expected and len(records) >= expected):
                break
            start += len(batch)  # actual size, not requested length
        return records
