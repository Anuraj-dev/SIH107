"""Allowlisted retrieval over local BIS metadata only. No external scraping."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ALLOWED_HOSTS = ("bis.gov.in", "crsbis.in", "manakonline.in", "lims.bis.gov.in", "standardsbis.bsbedge.com")

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


HINGLISH = {"pani": "water", "paani": "water", "peene": "drinking", "peyne": "drinking",
            "peyjal": "drinking water", "nal": "drinking water", "manak": "standard",
            "sona": "gold", "chandi": "silver", "bijli": "electrical", "khilona": "toy",
            "khilauna": "toy", "saria": "steel bar", "panjikaran": "registration",
            "jaanch": "testing", "parikshan": "testing", "gehne": "jewellery"}

DEVNAGARI = {"पानी": "water", "पेय": "drinking", "पेयजल": "drinking water", "नल": "drinking water",
             "मानक": "standard", "सोना": "gold", "चाँदी": "silver", "चांदी": "silver",
             "बिजली": "electrical", "खिलौना": "toy", "सरिया": "steel bar",
             "पंजीकरण": "registration", "जाँच": "testing", "जांच": "testing",
             "परीक्षण": "testing", "गेहना": "jewellery", "गेहने": "jewellery",
             "बोतल": "bottle", "स्टील": "steel", "प्रयोगशाला": "lab", "हॉलमार्क": "hallmark",
             "कांच": "glass", "शीशा": "glass", "काँच": "glass"}


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
        conn = kb_store.connect(_kb_path())
        try:
            return (kb_store.load_standards(conn), kb_store.load_schemes(conn),
                    kb_store.load_labs(conn), kb_store.load_glossary(conn))
        finally:
            conn.close()
    stds = json.loads((DATA_DIR / "standards.json").read_text())["standards"]
    schemes = json.loads((DATA_DIR / "schemes.json").read_text())["schemes"]
    labs = json.loads((DATA_DIR / "labs.json").read_text())
    glossary = json.loads((DATA_DIR / "glossary.json").read_text())["glossary"]
    return stds, schemes, labs, glossary


def assert_allowlisted(url: str) -> None:
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    if not any(h in host for h in ALLOWED_HOSTS):
        raise ValueError(f"Blocked non-allowlisted source: {url}")


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
    # IS number exact match boosts strongly
    m = re.search(r"is\s*(\d+)", query.lower())
    if m and m.group(1) in std["is_number"]:
        score += 20.0
        hits.append(std["is_number"])
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
            for u in (s["source_url"],):
                assert_allowlisted(u)
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
    return (f'{std["is_number"]}:{std["year"]} — {std["title_en"]} '
            f'[{std["status"]}, last-checked {std["last_checked"]}] — Source: {std["source_url"]}')
