"""Single LLM-backed chat path with retrieved BIS evidence as model context."""
from __future__ import annotations

import logging

from .i18n_privacy import detect_lang, redact
from .rag_answer import build_rag_answer
from .rag_llm import (
    is_configured,
    is_runtime_identity_query,
    is_underspecified_standard_query,
)
from .rag_config import load_llm_config, load_rag_config
from . import threads as threadmod

log = logging.getLogger("bis.api")

_DIAGNOSTIC_REASON_CODES = {
    "below_relevance_threshold": "relevance_threshold",
    "insufficient_query_term_overlap": "missing_query_terms",
    "no_relevance_overlap": "no_lexical_match",
    "top_k_limit": "outside_top_k",
    "combined_top_k_limit": "outside_top_k",
    "catalogue_limit": "outside_top_k",
    "duplicate_chunk": "duplicate_source",
    "duplicate_evidence": "duplicate_source",
    "source_diversity_limit": "source_diversity",
    "retrieval_error": "not_selected",
    "retrieval_disabled": "not_selected",
}


def _safe_diagnostic_branch(*, enabled: bool, evidence: list[dict],
                            document_searched: bool,
                            catalogue_searched: bool) -> str:
    if not enabled:
        return "disabled"
    if not evidence:
        return "no_results"
    if document_searched and catalogue_searched:
        return "hybrid"
    if document_searched:
        return "document"
    if catalogue_searched:
        return "catalogue"
    return "no_results"


def _diagnostic_reason_counts(reasons: dict[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for reason, count in reasons.items():
        code = _DIAGNOSTIC_REASON_CODES.get(reason, "not_selected")
        normalized[code] = normalized.get(code, 0) + int(count)
    return normalized


def _rag_lookup(text: str, top_k: int | None = None,
                _conn=None) -> tuple[list[dict], dict]:
    """Fetch relevant document and catalogue evidence without rendering it.

    Catalogue records are explicitly tagged as metadata-only context. The
    bounded diagnostics contain retrieval metadata, never the query or passage
    text.
    """
    cfg: dict = {}
    try:
        from .rag_retriever import search_rag
        from .catalogue_search import search_catalogue

        cfg = load_rag_config()
        if not cfg.get("enabled"):
            cfg["retrieval_diagnostics"] = {
                "branch": "disabled",
                "branches": {}, "selected_count": 0, "rejected_count": 0,
                "rejection_reasons": {"not_selected": 1},
                "results": [], "selected": [],
            }
            return [], cfg
        final_top_k = max(1, int(top_k or cfg.get("top_k", 5)))
        minimum_relevance = max(0.0, float(cfg.get("minimum_relevance", 0.25)))
        catalogue_top_k = max(1, int(cfg.get("catalogue_top_k", final_top_k)))
        document_diag: dict = {}
        catalogue_diag: dict = {}
        try:
            documents = search_rag(
                text,
                top_k=final_top_k,
                db_path=cfg.get("db_path"),
                lexical_weight=cfg.get("weight_lexical", 1.0),
                semantic_weight=cfg.get("weight_semantic", 0.3),
                exact_boost=cfg.get("exact_boost", 50.0),
                semantic=cfg.get("semantic", True),
                embedding_model=cfg.get("embedding_model", ""),
                minimum_relevance=minimum_relevance,
                diagnostics=document_diag,
                _conn=_conn,
            )
        except Exception:
            log.exception("BIS document retrieval branch failed")
            documents = []
            document_diag = {"branch": "document_chunks", "candidate_count": 0,
                             "selected_count": 0, "rejected_count": 0,
                             "rejection_reasons": {"retrieval_error": 1},
                             "selected": []}
        try:
            catalogue = search_catalogue(
                text, db_path=cfg.get("db_path"), limit=catalogue_top_k,
                minimum_relevance=minimum_relevance, diagnostics=catalogue_diag,
                _conn=_conn,
            )
        except Exception:
            log.exception("BIS catalogue retrieval branch failed")
            catalogue = []
            catalogue_diag = {"branch": "catalogue_records", "candidate_count": 0,
                              "selected_count": 0, "rejected_count": 0,
                              "rejection_reasons": {"retrieval_error": 1},
                              "selected": []}

        # Normalize catalogue rows to the same evidence contract as document
        # chunks. The explicit limits are also consumed by the answer prompt.
        catalogue_evidence = [{
            **item,
            "evidence_type": "catalogue_record",
            "doc_type": item.get("type_name") or "catalogue metadata",
            "heading": "",
            "chunk_text": "",
            "source_file": "",
            "metadata_only": True,
            "metadata_notice": "Catalogue metadata only; full standard text was not retrieved.",
            "metadata_scope": ["designation", "title", "department", "type", "date"],
            "unsupported_claims": [
                "clause-level scope", "technical requirements",
                "current legal applicability", "QCO or certification",
                "compliance", "product suitability",
            ],
            "selection_reason": (
                "exact_designation" if item.get("exact_match") else
                "relevance_threshold_passed"),
        } for item in catalogue]

        candidates = [*documents, *catalogue_evidence]
        candidates.sort(key=lambda item: (
            -float(item.get("relevance", 0.0)),
            not bool(item.get("exact_match")),
            item.get("evidence_type") != "document_chunk",
            -float(item.get("score", 0.0)),
        ))
        evidence: list[dict] = []
        reasons: dict[str, int] = {}
        merge_reasons: dict[str, dict[str, int]] = {}
        seen: set[tuple] = set()
        per_standard: dict[str, int] = {}
        # Count branch-level rejections already recorded by the retrievers.
        for branch_diag in (document_diag, catalogue_diag):
            for reason, count in branch_diag.get("rejection_reasons", {}).items():
                reasons[reason] = reasons.get(reason, 0) + int(count)
        for candidate_index, item in enumerate(candidates):
            branch = item.get("evidence_type", "document_chunk")
            if len(evidence) >= final_top_k:
                remaining = candidates[candidate_index:]
                reasons["combined_top_k_limit"] = len(remaining)
                for skipped in remaining:
                    skipped_branch = skipped.get("evidence_type", "document_chunk")
                    branch_reasons = merge_reasons.setdefault(skipped_branch, {})
                    branch_reasons["combined_top_k_limit"] = (
                        branch_reasons.get("combined_top_k_limit", 0) + 1)
                break
            if item.get("evidence_type") == "catalogue_record":
                key = ("catalogue", item.get("standard_id") or item.get("standard_number"))
            else:
                key = ("document", item.get("chunk_id") or item.get("doc_id"),
                       item.get("chunk_index"))
            if key in seen:
                reasons["duplicate_evidence"] = reasons.get("duplicate_evidence", 0) + 1
                branch_reasons = merge_reasons.setdefault(branch, {})
                branch_reasons["duplicate_evidence"] = (
                    branch_reasons.get("duplicate_evidence", 0) + 1)
                continue
            standard = item.get("standard_number") or str(key[1])
            if per_standard.get(standard, 0) >= 2:
                reasons["source_diversity_limit"] = reasons.get(
                    "source_diversity_limit", 0) + 1
                branch_reasons = merge_reasons.setdefault(branch, {})
                branch_reasons["source_diversity_limit"] = (
                    branch_reasons.get("source_diversity_limit", 0) + 1)
                continue
            seen.add(key)
            per_standard[standard] = per_standard.get(standard, 0) + 1
            evidence.append(item)
        evidence = evidence[:final_top_k]
        for rank, item in enumerate(evidence, 1):
            item["rank"] = rank
            item["relevance_reason"] = item.get(
                "selection_reason", "relevance_threshold_passed")
        branch_counts = {
            "document_chunks": int(document_diag.get("candidate_count", 0)),
            "catalogue_records": int(catalogue_diag.get("candidate_count", 0)),
        }
        branch_selected = {
            branch: sum(1 for item in evidence if item.get("evidence_type") == evidence_type)
            for branch, evidence_type in (
                ("document_chunks", "document_chunk"),
                ("catalogue_records", "catalogue_record"),
            )
        }
        total_candidates = sum(branch_counts.values())
        branch_results = {}
        for branch in ("document_chunks", "catalogue_records"):
            branch_reasons = dict(
                (document_diag if branch == "document_chunks" else catalogue_diag)
                .get("rejection_reasons", {}))
            for reason, count in merge_reasons.get(
                    "document_chunk" if branch == "document_chunks" else
                    "catalogue_record", {}).items():
                branch_reasons[reason] = branch_reasons.get(reason, 0) + count
            branch_results[branch] = {
                "candidate_count": branch_counts[branch],
                "selected_count": branch_selected[branch],
                "rejected_count": max(0, branch_counts[branch] - branch_selected[branch]),
                "rejection_reasons": branch_reasons,
            }
        cfg["retrieval_diagnostics"] = {
            "branch": _safe_diagnostic_branch(
                enabled=True, evidence=evidence,
                document_searched=bool(document_diag),
                catalogue_searched=bool(catalogue_diag)),
            "branches": branch_results,
            "selected_count": len(evidence),
            "rejected_count": max(0, total_candidates - len(evidence)),
            "rejection_reasons": _diagnostic_reason_counts(reasons),
            "results": [
                {"rank": rank, "evidence_type": item.get("evidence_type", "document_chunk"),
                 "score": round(float(item.get("relevance", 0.0)), 6),
                 "source_id": str(item.get("standard_number") or "")[:64],
                 "selected": True}
                for rank, item in enumerate(evidence[:20], 1)
            ],
            "selected": [
                {"branch": item.get("evidence_type", "document_chunk"),
                 "rank": rank,
                 "score": round(float(item.get("relevance", 0.0)), 6),
                 "reason": item.get("selection_reason", "relevance_threshold_passed")}
                for rank, item in enumerate(evidence[:12], 1)
            ],
        }
        return evidence, cfg
    except Exception:
        log.exception("BIS corpus retrieval failed; the model will receive no evidence")
        return [], {"retrieval_diagnostics": {
            "branch": "no_results", "branches": {},
            "selected_count": 0, "rejected_count": 0,
            "rejection_reasons": {"not_selected": 1},
            "results": [], "selected": [],
        }}


def answer(query: str, lang: str | None = None,
           context: dict | None = None) -> dict:
    """Return an LLM answer or an explicit model-unavailable state.

    Every valid chat turn uses one model generation. BIS evidence only enters
    the prompt as context; this module never renders retrieved text as an
    answer or substitutes deterministic catalogue/slot responses.
    """
    q = (query or "").strip()
    resolved_lang = lang if lang in ("en", "hi") else detect_lang(q)
    turn_context = threadmod.normalize_context(context)

    try:
        llm_cfg = load_llm_config()
        configured = is_configured(llm_cfg)
    except Exception:
        log.exception("Could not load LLM configuration")
        llm_cfg = {}
        configured = False

    evidence: list[dict] = []
    rag_cfg: dict = {}
    if configured and not is_runtime_identity_query(q) \
            and not is_underspecified_standard_query(q):
        evidence, rag_cfg = _rag_lookup(q)

    response = build_rag_answer(
        q,
        resolved_lang,
        evidence,
        llm_cfg,
        history=turn_context["history"],
    )
    response["context"] = {
        "history": threadmod.push_history(
            turn_context["history"], redact(q)[:2000]) if q else turn_context["history"],
        "rounds": turn_context["rounds"],
        "force": turn_context["force"],
    }
    response["intent"] = "general"
    response["intent_confidence"] = "low"
    response["context_summary"] = ""
    if rag_cfg.get("retrieval_diagnostics") is not None:
        response["retrieval_diagnostics"] = rag_cfg["retrieval_diagnostics"]
    return response
