"""Citation verifier (plan §4 stage 3): output claims must match cited KB rows.

Checks:
- every IS number mentioned in text appears in citations (uncited IS -> violation)
- answered-with-IS-claims requires non-empty citations
- clause numbers require a cited row with non-empty section_ref (v1 KB has none,
  so clause wording can never pass until §2 section fields are populated + reviewed)
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger("bis.verifier")

# Case-sensitive IS so English "is 1 litre" is not Indian Standard 1.
IS_RE = re.compile(r"(?<![A-Za-z])IS\s*(\d+(?:-\d+)?)")
CLAUSE_RE = re.compile(r"clause\s*\d", re.IGNORECASE)

VIOLATION_COUNT = {"n": 0}  # surfaced via /metrics in Phase 6


def _cited_numbers(citations: list[str]) -> set[str]:
    out = set()
    for c in citations:
        out.update(IS_RE.findall(c or ""))
    return out


def verify(resp: dict, section_refs: dict[str, str] | None = None) -> list[str]:
    section_refs = section_refs or {}
    violations: list[str] = []
    text, cits = resp.get("text", ""), resp.get("citations", [])
    if resp.get("refused"):
        return violations
    mentioned = set(IS_RE.findall(text)) - {"0000"}  # demo row handled by status path
    cited = _cited_numbers(cits)
    if resp.get("kind") == "glossary":
        # Glossary answers use real IS numbers as illustrative examples, not claims.
        # They must still be REAL (present in KB) — just not necessarily cited.
        unknown = mentioned - set(section_refs)
        if unknown:
            violations.append(f"glossary mentions unknown IS numbers: {sorted(unknown)}")
        return violations
    missing = mentioned - cited
    if missing:
        violations.append(f"uncited IS numbers: {sorted(missing)}")
    if mentioned and not cits:
        violations.append("IS claims with zero citations")
    if CLAUSE_RE.search(text):
        if not any(section_refs.get(n) for n in mentioned):
            violations.append("clause number without sourced section_ref")
    if violations:
        VIOLATION_COUNT["n"] += 1
        log.warning("citation verifier trip", extra={"violations": violations})
    return violations


def section_map(stds: list[dict]) -> dict[str, str]:
    out = {}
    for s in stds:
        m = IS_RE.search(s.get("is_number", ""))
        if m:
            out[m.group(1)] = s.get("section_ref", "") or ""
    return out
