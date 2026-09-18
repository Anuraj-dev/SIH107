"""Scorers: keyword baseline (current behaviour) + BM25 challenger (Phase 2).

Both return (score, hits); `hits` (exact phrase/IS matches) is scorer-independent so
multi-turn grounding semantics hold across the flag. BM25 raw scores are affine-mapped
by BM25_SCALE, calibrated in eval/ab_compare.py — see its report before changing.
"""
from __future__ import annotations
import math
import re

from .retriever import _tokens

K1 = 1.5
B = 0.75
BM25_SCALE = 4.0  # calibrated: gold tops land 12-25, vague tops stay < DIRECT_SCORE


def doc_text(std: dict) -> str:
    return " ".join([std.get("is_number", ""), str(std.get("year", "")),
                     std.get("title_en", ""), std.get("scope_en", ""),
                     " ".join(std.get("category_keywords", []))])


class BM25Index:
    def __init__(self, stds: list[dict]):
        self.docs = [_tokens(doc_text(s)) for s in stds]
        self.tok_lists = [[t for t in sorted(d)] for d in self.docs]
        # term freq per doc + doc freq
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for toks in (doc_text(s) for s in stds):
            words = re.findall(r"[a-z0-9\u0900-\u097F]+", toks.lower())
            counts: dict[str, int] = {}
            for w in words:
                counts[w] = counts.get(w, 0) + 1
            self.tf.append(counts)
            for w in counts:
                df[w] = df.get(w, 0) + 1
        self.df = df
        self.n = max(1, len(stds))
        self.avgdl = sum(sum(c.values()) for c in self.tf) / self.n

    def raw(self, query: str, i: int) -> float:
        score = 0.0
        dl = sum(self.tf[i].values()) or 1
        for term in _tokens(query):
            if term not in self.df:
                continue
            idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            f = self.tf[i].get(term, 0)
            # also match singular/plural variants present in doc
            if f == 0 and term.endswith("s"):
                f = self.tf[i].get(term[:-1], 0)
            if f == 0:
                continue
            score += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * dl / self.avgdl))
        return score


def score_bm25(query: str, std: dict, index: BM25Index, i: int) -> tuple[float, list[str]]:
    """BM25 score (scaled) + scorer-independent grounding hits.

    Phrase/IS hits earn a fixed bonus so exact-phrase grounding keeps its
    discriminating power under BM25 (e.g. Hinglish "drinking water" -> IS 10500).
    """
    from .retriever import score_standard  # baseline hits only
    _, hits = score_standard(query, std)
    return index.raw(query, i) * BM25_SCALE + 3.0 * len(hits), hits
