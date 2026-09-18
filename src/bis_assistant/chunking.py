"""Cleaning + chunking for BIS extracted TXT corpus.

- clean_text(): strip PDF extraction noise (gazette running heads/footers,
  xxxGID markers, CG-DL lines, page counters, blank-line noise, repeated
  headers/footers, consecutive duplicate lines) without deleting substance.
- chunk_text(): prefer document headings / page boundaries when detectable,
  else ~500-token windows with ~100-token overlap.
  Token estimate: 1 token ~= 0.75 words -> 500 tokens ~= 375 words,
  100 tokens ~= 75 words.
"""
from __future__ import annotations

import hashlib
import re

CHUNK_WORDS = 375
OVERLAP_WORDS = 75

_GID_RE = re.compile(r"xxxGID[HE]xxx")
_CGDL_RE = re.compile(r"CG-DL-E-[\d\-]+")
_GI_PAGE_RE = re.compile(r"^\s*\d+\s+GI/\d+\s*(\(\d+\))?\s*$")
_GAZETTE_HEAD_RE = re.compile(
    r"^\s*(THE GAZETTE OF INDIA\s*:?\s*EXTRAORDINARY|"
    r"\[PART III[^\]]*\]|EXTRAORDINARY|PUBLISHED BY AUTHORITY|"
    r"PART III[—\-]Section 4)\s*$", re.IGNORECASE)
_TABLE_NUM_RE = re.compile(r"^\(\d+\)\s+(\(\d+\)\s*)+$")
_WS_RE = re.compile(r"[ \t]+")

# Heading candidates: schedule/notification blocks, product-manual heads,
# numbered clauses, all-caps short lines.
_HEADING_RES = [
    re.compile(r"^\s*(SCHEDULE|NOTIFICATION|PRODUCT MANUAL|BUREAU OF INDIAN STANDARDS"
               r"|EXTRAORDINARY|ANNEX(?:URE)?\b|CHAPTER\b|SECTION\b|PART\b).*$",
               re.IGNORECASE),
    re.compile(r"^\s*(?:\d{1,3}\s*\.)\s+[A-Z][A-Za-z ,\-–—()&/]{8,120}$"),
    re.compile(r"^\s*PM\s*/\s*IS\b.*$", re.IGNORECASE),
    re.compile(r"^\s*Sl\.\s*No\..*$", re.IGNORECASE),
]


def detect_heading(line: str) -> str | None:
    s = line.strip()
    if not s or len(s) > 140:
        return None
    for rx in _HEADING_RES:
        if rx.match(s):
            return re.sub(r"\s+", " ", s)[:140]
    # ALL-CAPS short line heuristic (e.g. "METHODS OF SAMPLING ...")
    if len(s) >= 8 and len(s) <= 120 and s.upper() == s and re.search(r"[A-Z]{3,}", s):
        letters = re.sub(r"[^A-Za-z]", "", s)
        if len(letters) >= 8:
            return re.sub(r"\s+", " ", s)[:140]
    return None


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if _GID_RE.search(s) or _CGDL_RE.search(s):
        return True
    if _GI_PAGE_RE.match(s) or _GAZETTE_HEAD_RE.match(s) or _TABLE_NUM_RE.match(s):
        return True
    # Lone digits (page numbers) or "2  THE GAZETTE ..." running heads
    if re.match(r"^\d{1,4}$", s):
        return True
    if re.match(r"^\d+\s+THE GAZETTE OF INDIA", s, re.IGNORECASE):
        return True
    return False


def clean_text(raw: str) -> str:
    """Remove extraction noise; keep substantive content and heading lines."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    for ln in lines:
        ln2 = _WS_RE.sub(" ", ln).strip()
        # drop pure-noise lines, but keep SCHEDULE-type headings
        if _is_noise_line(ln2):
            # keep SCHEDULE header row content (has Sl./Standards words)
            if re.search(r"SCHEDULE|Standards Established|NOTIFICATION", ln2, re.IGNORECASE) \
                    and len(ln2) > 12:
                kept.append(ln2)
            continue
        kept.append(ln2)
    # Drop repeated header/footer lines (>=4 occurrences, short) — gazette
    # running heads repeat every page; body lines rarely repeat verbatim.
    from collections import Counter
    counts = Counter(k for k in kept if k and len(k) <= 120)
    filtered = [k for k in kept
                if not (len(k) <= 120 and counts.get(k, 0) >= 4
                        and re.search(r"GAZETTE|EXTRAORDINARY|PUBLISHED BY AUTHORITY"
                                      r"|BUREAU OF INDIAN STANDARDS|Department of Consumer",
                                      k, re.IGNORECASE))]
    # Collapse consecutive duplicate lines (extraction echoes)
    dedup: list[str] = []
    for k in filtered:
        if dedup and k and k == dedup[-1]:
            continue
        dedup.append(k)
    # Collapse 3+ blank runs to max 2 (blanks are "" entries)
    out: list[str] = []
    blanks = 0
    for k in dedup:
        if not k:
            blanks += 1
            if blanks <= 2:
                out.append(k)
        else:
            blanks = 0
            out.append(k)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _word_chunks(words: list[str], max_words: int = CHUNK_WORDS,
                 overlap: int = OVERLAP_WORDS) -> list[list[str]]:
    if not words:
        return []
    if len(words) <= max_words:
        return [words]
    chunks: list[list[str]] = []
    start = 0
    step = max(1, max_words - overlap)
    while start < len(words):
        chunks.append(words[start:start + max_words])
        if start + max_words >= len(words):
            break
        start += step
    return chunks


def chunk_text(cleaned: str, max_words: int = CHUNK_WORDS,
               overlap: int = OVERLAP_WORDS) -> list[dict]:
    """Split cleaned text into retrieval chunks.

    Returns [{chunk_text, heading, char_start, char_end}]; offsets index into
    `cleaned`. Sections split on detected headings first; long sections fall
    back to overlapping word windows.
    """
    lines = cleaned.split("\n")
    # Build (line, offset) map for char offsets
    offsets: list[int] = []
    pos = 0
    for i, ln in enumerate(lines):
        offsets.append(pos)
        pos += len(ln) + (1 if i < len(lines) - 1 else 0)

    sections: list[dict] = []  # {lines:[(idx,line)], heading}
    cur = {"heading": "", "items": []}
    for idx, ln in enumerate(lines):
        h = detect_heading(ln)
        if h and ln.strip():
            if cur["items"]:
                sections.append(cur)
            cur = {"heading": h, "items": [(idx, ln)]}
        else:
            cur["items"].append((idx, ln))
    if cur["items"]:
        sections.append(cur)
    if not sections:
        return []

    chunks: list[dict] = []
    seen_hashes: set[str] = set()
    for sec in sections:
        sec_text = "\n".join(ln for _, ln in sec["items"]).strip()
        if not sec_text:
            continue
        words = sec_text.split()
        # map word index -> char offset approx: find progressively
        for win in _word_chunks(words, max_words, overlap):
            ctext = " ".join(win).strip()
            if not ctext:
                continue
            # collapse single-word echo chunks
            key = hashlib.sha256(re.sub(r"\s+", " ", ctext.lower()).encode()).hexdigest()
            if key in seen_hashes:
                continue
            seen_hashes.add(key)
            # char offsets: locate window in section text, then in cleaned
            start_in_sec = sec_text.find(" ".join(win[:6])[:60])
            first_idx = sec["items"][0][0]
            base = offsets[first_idx] if first_idx < len(offsets) else 0
            cs = max(0, base + (start_in_sec if start_in_sec >= 0 else 0))
            chunks.append({
                "chunk_text": ctext if len(win) > 12 else sec_text[:2000],
                "heading": sec["heading"],
                "char_start": cs,
                "char_end": cs + len(ctext),
            })
            # If section fit in one window, stop (avoid overlap-only dupes)
            if len(words) <= max_words:
                break
    # Fallback: if cleaning removed everything structural, chunk raw words
    if not chunks and cleaned.strip():
        words = cleaned.split()
        for win in _word_chunks(words, max_words, overlap):
            ctext = " ".join(win)
            chunks.append({"chunk_text": ctext, "heading": "",
                           "char_start": 0, "char_end": len(cleaned)})
    # Token counts
    for c in chunks:
        c["token_count"] = max(1, int(len(c["chunk_text"].split()) / 0.75))
    return chunks


def normalize_for_dedup(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())
