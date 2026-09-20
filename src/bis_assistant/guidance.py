"""Adaptive certification guidance: tailor static scheme knowledge to the user.

The table critique is fair — scheme/process answers were one-size-fits-all.
This composer adds a short "For your situation" section derived from the
user's own context (product terms, stage: new/renewal/import/manufacture,
detected schemes) plus the scheme process steps already in the KB.

Verifier-safe by construction: the section never mints IS numbers (it only
reuses scheme keys and the user's own words) and never uses the word
"clause", so citation checks for metadata answers cannot trip.
"""
from __future__ import annotations

import re

_IS_RE = re.compile(r"IS\s*\d+", re.IGNORECASE)
_CLAUSE_RE = re.compile(r"clause", re.IGNORECASE)

_ADAPTIVE_INTENTS = {"certification_guidance", "process_explanation"}

_STAGE_ADVICE = {
    "new_licence": ("For a new licence: keep in-house test records ready before "
                    "applying, factory inspection usually follows the application."),
    "renewal": ("For a renewal: check that past test records and marking fee "
                "payments are up to date before applying."),
    "import": ("For imports: FMCS applies to foreign manufacturers. Indian "
               "importers should confirm the foreign unit holds a valid BIS licence."),
    "manufacture": ("For manufacturing: confirm the IS number and its QCO status "
                    "first. Production to a wrong or withdrawn number wastes a cycle."),
    "export": ("For exports: BIS certification covers the Indian market. Confirm "
               "the destination country's own requirements separately."),
}


def cited_numbers(citations: list[str]) -> set[str]:
    out: set[str] = set()
    for c in citations or []:
        for m in _IS_RE.finditer(c):
            out.add(re.sub(r"\s+", " ", m.group(0).strip()).upper())
    return out


def _safe(line: str, allowed_is: set[str]) -> str:
    """Drop lines that would trip the citation verifier (uncited IS refs)."""
    for m in _IS_RE.finditer(line):
        if re.sub(r"\s+", " ", m.group(0).strip()).upper() not in allowed_is:
            return ""
    if _CLAUSE_RE.search(line):
        return ""
    return line


def adaptive_section(query: str, intent: str, entities: dict,
                     schemes: list[dict], lang: str,
                     allowed_is: set[str]) -> list[str]:
    """Build verifier-safe adaptive lines, or [] when nothing applies."""
    if intent not in _ADAPTIVE_INTENTS:
        # Product→standard queries that surfaced a scheme (e.g. "which
        # standard ... is CRS needed?") also deserve tailored next steps.
        if intent != "recommend_standard" or not schemes:
            return []
    hi = lang == "hi"
    stage = (entities or {}).get("stage", "")
    products = (entities or {}).get("product_terms", [])[:3]
    out: list[str] = []
    if stage and stage in _STAGE_ADVICE:
        line = _safe(_STAGE_ADVICE[stage], allowed_is)
        if line:
            out.append("- " + line)
    if products and not _looks_like_gibberish(products):
        prod = ", ".join(products)
        line = ("Note: the steps below assume your product description "
                f"({prod}) maps to the cited scheme/standard — if the "
                "description changes, re-check the IS mapping first.")
        if hi:
            line = (f"Note: neeche ke charan aapke vivaran ({prod}) par adharit "
                    "hain. Vivaran badle to IS mapping dobara dekhen.")
        line = _safe(line, allowed_is)
        if line:
            out.append("- " + line)
    # Point at the most relevant scheme step already cited (no new claims).
    if schemes:
        key = schemes[0].get("key", "")
        if key:
            line = (f"Your nearest next step under {key}: "
                    f"{schemes[0].get('next_step', '')}".rstrip())
            if schemes[0].get("next_step"):
                line = _safe("- " + line, allowed_is)
                if line:
                    out.append(line)
    if not out:
        return []
    head = ("Aapki sthiti ke anusar:" if hi else "For your situation:")
    return [head, *out]


def _looks_like_gibberish(terms: list[str]) -> bool:
    # single unknown token with no vowels etc. — stay silent, don't echo junk
    if len(terms) == 1 and len(terms[0]) > 8:
        word = terms[0]
        if not re.search(r"[aeiou]", word):
            return True
    return False


def insert_before_footer(text: str, section: list[str]) -> str:
    """Splice adaptive lines ahead of the trailing footer (``---`` block)."""
    if not section:
        return text
    marker = "\n---\n"
    block = "\n".join([""] + section)
    if marker in text:
        return text.replace(marker, block + marker, 1)
    return text.rstrip() + "\n" + block + "\n"
