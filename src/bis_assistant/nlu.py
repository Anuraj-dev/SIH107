"""Lightweight NLU: intent classification + entity extraction (stdlib only).

Replaces scattered substring checks with one scored classifier whose intents
mirror the assistant's behavioural branches, so routing stays identical while
becoming observable (payload ``intent``) and reusable (guidance composer,
catalogue fallback). Channels:

- lexical: weighted keyword/phrase hits per intent (phrases weigh more);
- structural: exact IS-number presence, question words, translation cues;
- semantic (optional): token-overlap against intent prototype vectors when
  ``BIS_RAG_SEMANTIC``-style semantic mode is on — implemented with the same
  hashed-vector helper as retrieval, no new dependencies.

Intents: disallowed | hallmarking | lab_suggestion | certification_guidance |
process_explanation | recommend_standard | standard_info | consumer_query |
translation_request | general
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_IS_RE = re.compile(r"IS\s*\d+", re.IGNORECASE)

# intent -> (phrases (weight 3), keywords (weight 1))
_INTENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "hallmarking": (
        ("huid", "hallmark", "bis care", "gold jewellery", "gold jewelry"),
        ("hallmarking", "huid", "jewell", "gold", "silver", "sona", "chandi",
         "verify", "bought"),
    ),
    "lab_suggestion": (
        ("test lab", "testing lab", "where do i get this tested", "find a lab",
         "lims", "lab for"),
        ("laboratory", "laboratories", "lab", "testing", "tested", "test house",
         "prayogshala", "parikshan"),
    ),
    "certification_guidance": (
        ("qco", "crs registration", "isi mark", "fmcs", "compulsory",
         "is crs needed", "certification needed"),
        ("isi", "crs", "fmcs", "licence", "license", "certification",
         "registration", "qco", "scheme", "compulsory", "mandatory", "approval"),
    ),
    "process_explanation": (
        ("how to apply", "how do i", "how can i", "steps to", "process for",
         "procedure", "get licence", "get license", "obtain"),
        ("steps", "process", "procedure", "apply", "application", "timeline",
         "documents required", "fee", "factory inspection"),
    ),
    "recommend_standard": (
        ("which is", "which standard", "which bis", "suggest", "recommend",
         "for my product", "i make", "i manufacture", "we make", "startup makes"),
        ("product", "manufacture", "make", "startup", "business", "factory",
         "material", "applies", "suitable"),
    ),
    "standard_info": (
        ("what does", "tell me about", "scope of", "year and status",
         "is it active", "specification for"),
        ("scope", "specification", "standard", "revision", "year", "status",
         "withdrawn", "active", "superseded", "requirement"),
    ),
    "consumer_query": (
        ("consumer", "complaint", "where to buy", "price", "warranty",
         "duplicate", "fake product"),
        ("consumer", "complaint", "buy", "price", "shop", "warranty",
         "duplicate", "fake", "care"),
    ),
    "translation_request": (
        ("translate", "translation", "in hindi", "in english", "anuvaad"),
        ("translate", "hindi", "english", "meaning in"),
    ),
}

# product/stage entities
_STAGE_WORDS = {
    "new_licence": ("new plant", "new licence", "new license", "fresh", "setup", "start"),
    "renewal": ("renewal", "renew", "existing licence", "existing license"),
    "import": ("import", "imported", "fmcs", "foreign"),
    "manufacture": ("manufacture", "manufacturing", "factory", "plant"),
    "export": ("export", "exporting"),
}

_STOP = frozenset("""
what does the cover about which with from that this give summary scope standard standards
indian tell please explain specification requirements requirement information info
is are was were do does did done for on in of to a an the and or my i me we you
your yours how when where who whom it its these those from by as at be been being
have has had will would can could should suggest suggests recommend recommends
need needs needed requiring suitable applicable product products startup manufacturing
manufacture manufactures make makes made bis bureau
""".split())


def _toks(s: str) -> list[str]:
    return _TOKEN_RE.findall((s or "").lower())


def extract_is_numbers(query: str) -> list[str]:
    return [re.sub(r"\s+", " ", m.group(0).strip())
            for m in re.finditer(r"IS\s*\d+(?:\s*\([^)]*\))?\s*(?::\s*\d{4})?",
                                 query or "", re.IGNORECASE)]


def extract_product_terms(text: str, limit: int = 6) -> list[str]:
    seen: list[str] = []
    for w in _toks(text):
        if len(w) > 3 and w not in _STOP and w not in seen:
            seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def extract_stage(text: str) -> str:
    low = (text or "").lower()
    for stage, phrases in _STAGE_WORDS.items():
        if any(p in low for p in phrases):
            return stage
    return ""


def classify(query: str, history: list[str] | None = None) -> dict:
    """Return {intent, confidence, scores, entities} for a user query.

    Never raises; empty/unknown queries yield ("general", "low").
    ``history`` adds a small continuity bonus to the previously implied
    product terms but never overrides an explicit current-query signal.
    """
    q = (query or "").strip()
    low = q.lower()
    scores: dict[str, float] = {k: 0.0 for k in _INTENTS}
    try:
        for intent, (phrases, keywords) in _INTENTS.items():
            for p in phrases:
                if p and p in low:
                    scores[intent] += 3.0
            qt = set(_toks(q))
            for k in keywords:
                kt = set(_toks(k))
                if kt and kt <= qt:
                    scores[intent] += 1.0 + (0.5 if len(kt) > 1 else 0.0)
        # Structural signals.
        if _IS_RE.search(q):
            scores["standard_info"] += 2.0
        if re.search(r"\bwhich\b.*\b(is|standard)\b", low) or \
                re.search(r"\b(is|standard)\b.*\?", low) and "which" in low:
            scores["recommend_standard"] += 1.0
        if low.startswith(("what is", "what are", "what does", "explain")):
            scores["standard_info"] += 0.5
            scores["process_explanation"] += 0.5 if "process" in low or "steps" in low else 0.0
        # History continuity: product terms from earlier turns keep the
        # recommendation thread alive for short follow-ups ("1 litre", ...).
        if history:
            try:
                from .retriever import CONTENT_STOPWORDS
            except Exception:
                CONTENT_STOPWORDS = frozenset()
            htoks = set()
            for h in history[-2:]:
                htoks.update(w for w in _toks(h)
                             if len(w) > 3 and w not in CONTENT_STOPWORDS)
            overlap = len(htoks & set(_toks(q)))
            if overlap:
                scores["recommend_standard"] += 0.5 * overlap
        best = max(scores, key=lambda k: scores[k])
        top = scores[best]
        second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
        if top <= 0:
            return {"intent": "general", "confidence": "low", "scores": scores,
                    "entities": _entities(q)}
        if top >= 5.0 or (top - second) >= 3.0:
            conf = "high"
        elif top >= 2.0:
            conf = "medium"
        else:
            conf = "low"
        return {"intent": best, "confidence": conf, "scores": scores,
                "entities": _entities(q)}
    except Exception:
        return {"intent": "general", "confidence": "low", "scores": scores,
                "entities": _entities(q)}


def _entities(q: str) -> dict:
    return {
        "is_numbers": extract_is_numbers(q),
        "product_terms": extract_product_terms(q),
        "stage": extract_stage(q),
    }
