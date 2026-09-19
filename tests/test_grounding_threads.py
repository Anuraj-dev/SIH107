"""Pins for the grounding + threads extraction (arch/deepen-grounding-threads).

These modules own decisions formerly inline in assistant/server; every test
below asserts delegation equivalence or unchanged truncation constants so the
data path (retriever/kb_store/data/*.json) stays untouched and green.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bis_assistant import grounding, threads
from bis_assistant import slots


def test_grounding_thresholds_have_defaults():
    live, fallback = grounding.thresholds(), dict(grounding.FALLBACK_THRESHOLDS)
    assert all(live[k] == v for k, v in fallback.items())  # live config may add keys


def test_slots_public_accessor():
    assert slots.active_slots() is slots._active()


def test_threads_normalize_and_reset():
    assert threads.normalize_context(None) == {"history": [], "rounds": 0, "force": False}
    assert threads.normalize_context({"history": ["a"], "rounds": "2", "force": 1}) == {
        "history": ["a"], "rounds": 2, "force": True}
    assert threads.reset_context() == {"history": [], "rounds": 0, "force": False}
    assert threads.with_force({"history": ["a"], "rounds": 1, "force": False})["force"] is True


def test_threads_truncation_limits_unchanged():
    assert threads.HISTORY_LIMIT == 6 and threads.BRIDGE_LIMIT == 4
    assert threads.push_history(["a", "b"], "c") == ["a", "b", "c"]
    assert threads.push_history([str(i) for i in range(8)], "x") == [str(i) for i in range(3, 8)] + ["x"]
    assert threads.bridge_history([str(i) for i in range(6)]) == ["2", "3", "4", "5"]
    assert threads.rounds_from(None, default=7) == 7
    assert threads.rounds_from({"rounds": 3}, default=7) == 3
    assert threads.combined_query(["steel bottle"], "vacuum") == "steel bottle vacuum"


def test_assess_exact_is_direct():
    from bis_assistant.retriever import retrieve
    t = grounding.thresholds()
    combined = "IS 10500 year and status"
    res = retrieve(combined)
    a = grounding.assess(combined, res["candidates"], threads.new_context(), t)
    assert a["exact"] is True and a["direct"]
