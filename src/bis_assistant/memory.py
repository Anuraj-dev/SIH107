"""Conversational memory beyond slots: thread summary + query expansion.

- summarize_thread(history): short extractive summary (first query + salient
  keywords of recent turns) used for payload transparency and history-aware
  retrieval. Deterministic, stdlib-only.
- expand_query(query, history): retrieval-oriented rewrite — the raw query
  plus salient history keywords missing from it. Used ONLY for corpus /
  catalogue retrieval so curated metadata behaviour never drifts.
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

_STOP = frozenset("""
what does the cover about which with from that this give summary scope standard standards
indian tell please explain requirements requirement information info
is are was were do does did done for on in of to a an the and or my i me we you
your yours how when where who whom it its these those from by as at be been being
have has had will would can could should just very much more most also only
suggest suggests recommend recommends need needs needed suitable applicable product
products startup manufacturing manufacture makes make made bis
mujhe mujhko kya hai ka ki ke ko me men ne par ya aur nahin nahi karke liye
""".split())


def salient_terms(text: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for w in _TOKEN_RE.findall((text or "").lower()):
        if len(w) > 3 and w not in _STOP and w not in seen:
            # skip bare years / pure digits
            if w.isdigit():
                continue
            seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def summarize_thread(history: list[str], max_chars: int = 280) -> str:
    """One-line extractive summary of the thread so far."""
    hist = [h for h in (history or []) if (h or "").strip()]
    if not hist:
        return ""
    try:
        first = " ".join(hist[0].split())
        recent_terms: list[str] = []
        for h in hist[-2:]:
            for w in salient_terms(h):
                if w not in recent_terms:
                    recent_terms.append(w)
        # drop terms already prominent in the first query
        fresh = [w for w in recent_terms if w not in first.lower()][:6]
        summary = first
        if fresh:
            summary += " | focus: " + ", ".join(fresh)
        return summary[:max_chars]
    except Exception:
        return ""


def expand_query(query: str, history: list[str] | None) -> str:
    """Append salient history keywords missing from the query."""
    q = (query or "").strip()
    if not history:
        return q
    try:
        qtoks = set(_TOKEN_RE.findall(q.lower()))
        extra: list[str] = []
        for h in history[-3:]:
            for w in salient_terms(h, limit=6):
                if w not in qtoks and w not in extra:
                    extra.append(w)
                if len(extra) >= 6:
                    break
        return (q + " " + " ".join(extra)).strip() if extra else q
    except Exception:
        return q
