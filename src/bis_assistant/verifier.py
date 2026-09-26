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
SOURCE_RE = re.compile(r"\[Source\s+(\d+)\]", re.IGNORECASE)
STANDARD_DESIGNATION_RE = re.compile(
    r"\bIS\s*(?P<base>\d+(?:-\d+)?)(?:\s*(?P<qualifier>\([^\n)]{1,80}\)))?"
    r"(?:\s*:\s*(?P<year>\d{4}))?",
    re.IGNORECASE,
)
CLAUSE_REF_RE = re.compile(
    r"\b(?:clause|section)\s*(?:no\.?\s*)?(\d+(?:\.\d+)*(?:\([a-z0-9]+\))?)",
    re.IGNORECASE,
)

_UNSUPPORTED_CATALOGUE_CLAIM_RE = re.compile(
    r"\b(?:requires?|requirement(?:s)?|must|shall|should|"
    r"specif(?:y|ies|ied|ication|ications)|covers?|applies?\s+to|"
    r"applicable\s+to|suitable\s+for|use|approved|certified|"
    r"compliance|compliant|certification|QCO|mandatory|mandated|"
    r"currently\s+applicable|in\s+force|effective)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"\b(?:not|no|cannot|can['’]t|does\s+not|doesn['’]t|do\s+not|"
    r"don['’]t|did\s+not|is\s+not|isn['’]t|are\s+not|aren['’]t|"
    r"without|unable\s+to|insufficient|unknown)\b",
    re.IGNORECASE,
)
_CONTRAST_BOUNDARY_RE = re.compile(
    r"\b(?:but|however|yet|nevertheless|instead)\b", re.IGNORECASE)
_METADATA_NOTICE_RE = re.compile(
    r"\b(?:catalog(?:ue)?\s+(?:record|entry|metadata|result|listing)|metadata[- ]only)\b",
    re.IGNORECASE,
)
_FULL_TEXT_LIMIT_RE = re.compile(
    r"\bfull\s+(?:standard\s+)?text\b.{0,70}\b(?:not\s+(?:been\s+)?retrieved|"
    r"wasn['’]t\s+retrieved|hasn['’]t\s+been\s+retrieved|"
    r"not\s+(?:available|provided|included)|missing|unavailable)\b|"
    r"\b(?:not\s+(?:been\s+)?retrieved|not\s+(?:available|provided|included)|"
    r"wasn['’]t\s+retrieved|hasn['’]t\s+been\s+retrieved|"
    r"missing|unavailable)\b.{0,70}\bfull\s+(?:standard\s+)?text\b",
    re.IGNORECASE,
)

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


def evidence_type(evidence: dict) -> str:
    """Return the stable evidence kind, failing safely for untyped records."""
    kind = str(evidence.get("evidence_type", "")).strip().lower()
    if kind in ("document_chunk", "catalogue_record"):
        return kind
    # Older retrieval rows have no explicit type. Non-empty body text is the
    # only safe signal that the row is a retrieved document passage.
    return "document_chunk" if str(evidence.get("chunk_text", "")).strip() else "catalogue_record"


def _standard_key(value: str) -> str:
    match = IS_RE.search(value or "")
    return match.group(1) if match else ""


def _designation_key(value: str) -> tuple[str, str, str, str]:
    match = STANDARD_DESIGNATION_RE.search(value or "")
    if not match:
        return "", "", "", ""
    qualifier = match.group("qualifier") or ""
    part = re.search(r"\bpart\s*(\d+)", qualifier, re.IGNORECASE)
    section = re.search(r"\bsec(?:tion)?\s*(\d+)", qualifier, re.IGNORECASE)
    return (
        match.group("base"),
        part.group(1) if part else "",
        section.group(1) if section else "",
        match.group("year") or "",
    )


def _designation_matches(mentioned: str, source: dict) -> bool:
    mentioned_key = _designation_key(mentioned)
    source_key = _designation_key(str(source.get("standard_number", "")))
    if not mentioned_key[0] or mentioned_key[0] != source_key[0]:
        return False
    # When the answer names a part, section, or edition explicitly, it must be
    # present in the source's designation or passage. A conflicting designation
    # in the source metadata always wins over incidental cross-references.
    support_text = " ".join((
        str(source.get("chunk_text", "")),
        str(source.get("published_on", "")),
    ))
    support_keys = [
        _designation_key(match.group(0))
        for match in STANDARD_DESIGNATION_RE.finditer(support_text)
        if match.group("base") == mentioned_key[0]
    ]
    for index, mentioned_value in enumerate(mentioned_key[1:], 1):
        if not mentioned_value:
            continue
        source_value = source_key[index]
        if source_value:
            if source_value != mentioned_value:
                return False
        elif not any(candidate[index] == mentioned_value for candidate in support_keys):
            if index == 3 and str(source.get("published_on", "")).strip()[:4] == mentioned_value:
                continue
            return False
    return True


def _sentence_bounds(text: str, position: int) -> tuple[int, int]:
    """Find a compact sentence span around a match for local citation checks."""
    left = 0
    for boundary in re.finditer(r"[.!?]+\s+|\n+", text):
        if boundary.end() <= position:
            left = boundary.end()
        elif boundary.start() >= position:
            return left, boundary.start()
    return left, len(text)


def _positive_unsupported_catalogue_claim(text: str) -> bool:
    for match in _UNSUPPORTED_CATALOGUE_CLAIM_RE.finditer(text):
        sentence_start, _ = _sentence_bounds(text, match.start())
        before = text[sentence_start:match.start()]
        # A negation in an earlier sentence or contrastive clause does not
        # negate this claim. Keep the local window to avoid distant scope.
        before = _CONTRAST_BOUNDARY_RE.split(before)[-1][-48:]
        if not _NEGATION_RE.search(before):
            return True
    return False


def verify_grounded_response(text: str, evidence: list[dict]) -> list[str]:
    """Check generated designations, source markers, clause refs, and metadata limits.

    This deliberately validates citation linkage and high-risk claim forms, not
    semantic entailment. The model remains responsible for synthesis; on failure
    the caller can request one bounded repair rather than exposing unsafe text.
    """
    violations: list[str] = []
    rows = evidence[:5]
    known_keys = {_standard_key(str(row.get("standard_number", "")))
                  for row in rows}
    known_keys.discard("")

    for marker in SOURCE_RE.finditer(text):
        index = int(marker.group(1)) - 1
        if index < 0 or index >= len(rows):
            violations.append("invalid_source_marker")
            break

    for mention in STANDARD_DESIGNATION_RE.finditer(text):
        number = mention.group("base")
        if number not in known_keys:
            violations.append("unsupported_standard_designation")
            continue
        start, end = _sentence_bounds(text, mention.start())
        sentence = text[start:end]
        cited_rows = []
        for marker in SOURCE_RE.finditer(sentence):
            index = int(marker.group(1)) - 1
            if 0 <= index < len(rows):
                cited_rows.append(rows[index])
        if not cited_rows:
            violations.append("standard_without_source_marker")
        elif not any(_designation_matches(mention.group(0), row)
                     for row in cited_rows):
            violations.append("designation_source_mismatch")

    for clause in CLAUSE_REF_RE.finditer(text):
        start, end = _sentence_bounds(text, clause.start())
        sentence = text[start:end]
        cited_rows = []
        for marker in SOURCE_RE.finditer(sentence):
            index = int(marker.group(1)) - 1
            if 0 <= index < len(rows):
                cited_rows.append(rows[index])
        clause_text = clause.group(1).lower()
        supported = any(
            evidence_type(row) == "document_chunk"
            and re.search(rf"(?<!\d){re.escape(clause_text)}(?!\d)",
                          str(row.get("chunk_text", "")), re.IGNORECASE)
            for row in cited_rows
        )
        if not supported:
            violations.append("unsupported_clause_reference")

    catalogue_only = bool(rows) and all(
        evidence_type(row) == "catalogue_record" for row in rows)
    cited_catalogue = False
    catalogue_claim_without_document = False
    checked_spans: set[tuple[int, int]] = set()
    for marker in SOURCE_RE.finditer(text):
        start, end = _sentence_bounds(text, marker.start())
        if (start, end) in checked_spans:
            continue
        checked_spans.add((start, end))
        sentence = text[start:end]
        cited_rows = []
        for sentence_marker in SOURCE_RE.finditer(sentence):
            index = int(sentence_marker.group(1)) - 1
            if 0 <= index < len(rows):
                cited_rows.append(rows[index])
        sentence_uses_catalogue = any(
            evidence_type(row) == "catalogue_record" for row in cited_rows)
        if sentence_uses_catalogue:
            cited_catalogue = True
            if (_positive_unsupported_catalogue_claim(sentence)
                    and not any(evidence_type(row) == "document_chunk"
                                for row in cited_rows)):
                catalogue_claim_without_document = True

    if catalogue_only or cited_catalogue:
        if not _METADATA_NOTICE_RE.search(text) or not _FULL_TEXT_LIMIT_RE.search(text):
            violations.append("catalogue_limit_not_disclosed")
    if catalogue_claim_without_document or (
            catalogue_only and _positive_unsupported_catalogue_claim(text)):
        violations.append("unsupported_catalogue_claim")

    # Keep issue codes stable and bounded for the one repair prompt. Do not put
    # raw answer, query, or retrieved text into diagnostics or logs.
    return list(dict.fromkeys(violations))


def section_map(stds: list[dict]) -> dict[str, str]:
    out = {}
    for s in stds:
        m = IS_RE.search(s.get("is_number", ""))
        if m:
            out[m.group(1)] = s.get("section_ref", "") or ""
    return out
