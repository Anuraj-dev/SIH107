"""Allowlisted retrieval over local BIS metadata only. No external scraping."""
from __future__ import annotations
import json
import logging
import os
import re
from pathlib import Path

from .allowlist import ALLOWED_HOSTS, assert_allowlisted  # noqa: F401

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
log = logging.getLogger("bis.retriever")

def _backend() -> str:
    import os
    return os.environ.get("BIS_RETRIEVAL_KB_BACKEND", "json")  # json | sqlite


def _kb_path() -> str:
    import os
    return os.environ.get("BIS_KB_PATH",
                          str(Path(__file__).resolve().parents[2] / "kb" / "bis.db"))

# Back-compat names (import-time snapshot; load_kb() reads env dynamically).
KB_BACKEND = _backend()
KB_PATH = _kb_path()

# In-process KB cache keyed by (db path, mtime): breadth KBs (~20k rows)
# must not be re-read from SQLite on every /chat call (p95 <2 s SLO).
# Callers only read the cached rows; mtime check keeps refreshes visible.
_KB_CACHE: dict = {}


HINGLISH = {"pani": "water", "paani": "water", "peene": "drinking", "peyne": "drinking",
            "peyjal": "drinking water", "nal": "drinking water", "manak": "standard",
            "sona": "gold", "chandi": "silver", "bijli": "electrical", "khilona": "toy",
            "khilauna": "toy", "saria": "steel bar", "panjikaran": "registration",
            "jaanch": "testing", "parikshan": "testing", "gehne": "jewellery",
            "taar": "wire cable", "tar": "wire", "balb": "bulb", "helmat": "helmet",
            "helmet": "helmet", "tayar": "tyre", "tyre": "tyre", "loha": "steel iron",
            "lakdi": "wood", "kagaz": "paper", "tel": "oil", "chini": "sugar",
            "aata": "flour", "cement": "cement", "khel": "toy", "dabaav": "pressure",
            "upkaran": "appliance"}

# Function words excluded when judging whether a query has TOPICAL overlap
# (weak-clarify tier). Without this, stopwords like do/on/is route journey
# queries into interrogation.
CONTENT_STOPWORDS = frozenset("""
is are was were do does did done for on in of to a an the and or my i me we you
your yours which what how when where who whom it its this that these those with
from by as at be been being have has had will would can could should s t ve re ll
mujhe mujhko kya hai ka ki ke ko me men ne par ya aur nahin nahi karke liye
""".split())

DEVNAGARI = {"पानी": "water", "पेय": "drinking", "पेयजल": "drinking water", "नल": "drinking water",
             "मानक": "standard", "सोना": "gold", "चाँदी": "silver", "चांदी": "silver",
             "बिजली": "electrical", "खिलौना": "toy", "सरिया": "steel bar",
             "पंजीकरण": "registration", "जाँच": "testing", "जांच": "testing",
             "परीक्षण": "testing", "गेहना": "jewellery", "गेहने": "jewellery",
             "बोतल": "bottle", "स्टील": "steel", "प्रयोगशाला": "lab", "हॉलमार्क": "hallmark",
             "कांच": "glass", "शीशा": "glass", "काँच": "glass",
             "तार": "wire", "केबल": "cable", "बल्ब": "bulb", "हेलमेट": "helmet",
             "टायर": "tyre", "लोहा": "steel", "लकड़ी": "wood", "कागज": "paper",
             "तेल": "oil", "चीनी": "sugar", "सीमेंट": "cement", "दबाव": "pressure",
             "उपकरण": "appliance", "पाइप": "pipe"}


def _tokens(s: str) -> set[str]:
    toks = re.findall(r"[a-z0-9\u0900-\u097F]+", s.lower())
    out: set[str] = set()
    for t in toks:
        out.add(t)
        if t in HINGLISH:
            out.update(re.findall(r"[a-z0-9]+", HINGLISH[t]))
        if t in DEVNAGARI:
            out.update(re.findall(r"[a-z0-9]+", DEVNAGARI[t]))
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            out.add(t[:-1])  # singular form: bulbs->bulb, cables->cable
    return out


def load_kb():
    if _backend() == "sqlite":
        from . import kb_store
        path = _kb_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = -1
        key = (path, mtime)
        if _KB_CACHE.get("key") != key:  # (re)load on DB change; stat is cheap
            try:
                conn = kb_store.connect(path) if mtime >= 0 else None
                if conn is None:
                    _KB_CACHE.pop("kb", None)
                    _KB_CACHE["key"] = key
                else:
                    try:
                        stds = kb_store.load_standards(conn)
                        if stds:  # populated SQLite KB (breadth v2)
                            _KB_CACHE.update(key=key, kb=(
                                stds, kb_store.load_schemes(conn),
                                kb_store.load_labs(conn), kb_store.load_glossary(conn)))
                        else:
                            _KB_CACHE.pop("kb", None)
                            _KB_CACHE["key"] = key
                    finally:
                        conn.close()
            except Exception:
                _KB_CACHE.pop("kb", None)
                _KB_CACHE["key"] = key
        if "kb" in _KB_CACHE and _KB_CACHE.get("key") == key:
            return _KB_CACHE["kb"]
        # empty/missing SQLite KB (fresh clone) -> JSON fallback, never refuse-all
    stds = json.loads((DATA_DIR / "standards.json").read_text())["standards"]
    schemes = json.loads((DATA_DIR / "schemes.json").read_text())["schemes"]
    labs = json.loads((DATA_DIR / "labs.json").read_text())
    glossary = json.loads((DATA_DIR / "glossary.json").read_text())["glossary"]
    return stds, schemes, labs, glossary


# Shared IS-reference parsing (issue #4 P0-4): one normalizer for the
# metadata scorer, the grounding exact-match and the RAG boost, so
# `IS-10500` hits, `IS 10` never prefix-matches `IS 10500`, and part
# designations compare structurally instead of by substring.
IS_REF_RE = re.compile(
    r"IS\s*-?\s*\d+(?:\s*\([^)]*\))?\s*(?::\s*\d{4})?", re.IGNORECASE)


def extract_is_refs(text: str) -> list[str]:
    """Raw IS designations in text, e.g. ['IS 101 (Part 2/Sec 6):2026']."""
    return [re.sub(r"\s+", " ", m.group(0).strip())
            for m in IS_REF_RE.finditer(text or "")]


def normalize_is_ref(ref: str) -> str:
    """Canonical form: `IS 101(PART 2/SEC 6):2026`-style, hyphen-tolerant."""
    s = (ref or "").upper().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*([-():/])\s*", r"\1", s)
    s = re.sub(r"^IS\s*-?\s*", "IS ", s)
    return s


def _strip_year(ref: str) -> str:
    return re.sub(r":\d{4}$", "", ref)


def is_number_base(ref: str) -> str:
    """Base digits of a designation: 'IS 302-1'/'IS 302' -> '302'."""
    m = re.search(r"IS\s*[A-Z/]*\s*(\d+)", (ref or "").upper())
    return m.group(1) if m else ""


def is_exact_is_match(query: str, std_is_number: str) -> bool:
    """Full-designation equality (year-insensitive when the query omits it)."""
    std_n = normalize_is_ref(std_is_number)
    std_ny = _strip_year(std_n)
    for ref in extract_is_refs(query):
        n = normalize_is_ref(ref)
        if n == std_n or _strip_year(n) == std_ny:
            return True
    return False


def score_standard(query: str, std: dict) -> tuple[float, list[str]]:
    q = _tokens(query)
    hits: list[str] = []
    score = 0.0
    blob = " ".join([std["is_number"], std.get("year", ""), std.get("title_en", ""),
                     std.get("scope_en", ""), " ".join(std.get("category_keywords", []))])
    bt = _tokens(blob)
    overlap = q & bt
    score += len(overlap) * 2.0
    for kw in std.get("category_keywords", []):
        kt = _tokens(kw)
        if kt and kt <= q:
            score += 5.0
            hits.append(kw)
    # IS number match: full designation boosts strongly (+hit); a bare base
    # number equal to the standard's base only nudges (no hit, never exact).
    if is_exact_is_match(query, std["is_number"]):
        score += 20.0
        hits.append(std["is_number"])
    else:
        q_bases = {is_number_base(r) for r in extract_is_refs(query)}
        q_bases.discard("")
        if q_bases and is_number_base(std["is_number"]) in q_bases:
            score += 8.0
    return score, hits


_BM25_CACHE: dict = {}


def _scorer() -> str:
    import os
    try:
        from .config import load as load_config
        default = load_config()["retrieval"].get("scorer", "keyword")
    except Exception:
        default = "keyword"
    return os.environ.get("BIS_RETRIEVAL_SCORER", default)


def retrieve(query: str, top_k: int = 3):
    from .verifier import section_map
    stds, schemes, labs, glossary = load_kb()
    scorer = _scorer()
    index = None
    if scorer == "bm25":
        from .scorers import BM25Index, score_bm25
        key = (len(stds), stds[0]["is_number"] if stds else "")
        if _BM25_CACHE.get("key") != key:
            _BM25_CACHE.update(key=key, index=BM25Index(stds))
        index = _BM25_CACHE["index"]
    ranked = []
    for i, s in enumerate(stds):
        if scorer == "bm25":
            sc, hits = score_bm25(query, s, index, i)
        else:
            sc, hits = score_standard(query, s)
        if sc > 0:
            try:
                assert_allowlisted(s.get("source_url") or "")
            except ValueError:
                log.warning("skipping KB row with bad source_url is_number=%s",
                            s.get("is_number", ""))
                continue
            ranked.append((sc, s, hits))
    ranked.sort(key=lambda x: -x[0])
    cands = [{"score": sc, "std": s, "hits": h,
              "confidence": "high" if sc >= 20 else ("medium" if sc >= 6 else "low")}
             for sc, s, h in ranked[:top_k]]
    # scheme match (skip punctuation-only name fragments like em-dashes)
    ql = query.lower()
    scheme_hits = [s for s in schemes if s["key"].lower() in ql or any(
        w in ql for w in s["name_en"].lower().split()[:4] if len(w) > 3 and w.isalnum())]
    # glossary match
    gloss_hits = [g for g in glossary if g["term"].lower().split()[0] in ql or g["term"].lower() in ql]
    return {"candidates": cands, "schemes": scheme_hits, "glossary": gloss_hits,
            "section_refs": section_map(stds), "scorer": scorer}


def format_citation(std: dict) -> str:
    assert_allowlisted(std["source_url"])
    return (f'{std["is_number"]}:{std["year"]}, {std["title_en"]} '
            f'[{std["status"]}, last-checked {std["last_checked"]}], Source: {std["source_url"]}')
