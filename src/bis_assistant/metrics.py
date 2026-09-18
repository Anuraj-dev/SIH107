"""In-process metrics (plan §7). Single-instance pilot; Prometheus scrapes /metrics.

Rollback: BIS_METRICS_ENABLED=false disables collection (Phase-6 flag).
"""
from __future__ import annotations
import os
import threading
from datetime import date

_lock = threading.Lock()
_counts: dict[str, int] = {}
_lat: list[int] = []


def enabled() -> bool:
    return os.environ.get("BIS_METRICS_ENABLED", "true").lower() in ("1", "true", "yes")


def incr(name: str, n: int = 1) -> None:
    if not enabled():
        return
    with _lock:
        _counts[name] = _counts.get(name, 0) + n


def observe_latency_ms(ms: int) -> None:
    if not enabled():
        return
    with _lock:
        _lat.append(ms)
        del _lat[:-500]


def reset() -> None:  # tests only
    with _lock:
        _counts.clear()
        _lat.clear()


def _pct(xs: list[int], p: float) -> int:
    if not xs:
        return 0
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * p))]


def kb_staleness_days() -> int:
    try:
        from .retriever import load_kb
        dates = [s.get("last_checked", "") for s in load_kb()[0] if s.get("last_checked")]
        if not dates:
            return -1
        return max(0, (date.today() - date.fromisoformat(max(dates)[:10])).days)
    except Exception:
        return -1


def snapshot() -> dict:
    from . import verifier
    with _lock:
        lat = list(_lat)
        counts = dict(_counts)
    out = dict(counts)
    out["chat_latency_p50_ms"] = _pct(lat, 0.5)
    out["chat_latency_p95_ms"] = _pct(lat, 0.95)
    out["citation_fail_total"] = verifier.VIOLATION_COUNT["n"]
    out["kb_staleness_days"] = kb_staleness_days()
    return out


def render_prometheus() -> str:
    lines = []
    for k in sorted(snapshot()):
        lines.append(f"bis_{k} {snapshot()[k]}")
    return "\n".join(lines) + "\n"
