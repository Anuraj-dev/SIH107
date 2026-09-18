import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant import verifier
from bis_assistant.assistant import answer
from bis_assistant.retriever import load_kb, retrieve
from bis_assistant.scorers import BM25Index, score_bm25


def test_bm25_ranks_steel_bottle_top():
    stds, _, _, _ = load_kb()
    idx = BM25Index(stds)
    scored = sorted(((idx.raw("vacuum insulated stainless steel water bottle", i), s["is_number"])
                     for i, s in enumerate(stds)), reverse=True)
    assert scored[0][1] == "IS 17803"


def test_bm25_hits_match_baseline():
    stds, _, _, _ = load_kb()
    idx = BM25Index(stds)
    i = next(i for i, s in enumerate(stds) if s["is_number"] == "IS 10500")
    _, hits = score_bm25("IS 10500 drinking water", stds[i], idx, i)
    assert "IS 10500" in hits


def test_verifier_catches_uncited_is():
    resp = {"text": "Use IS 9999 for everything.", "citations": [], "refused": False}
    assert verifier.verify(resp, {}) != []


def test_verifier_catches_clause_without_section():
    resp = {"text": "Per IS 694 clause 5.2 the cable must ...",
            "citations": ["IS 694:2010 — Cable [Active, last-checked x] — Source: y"],
            "refused": False}
    assert verifier.verify(resp, {"694": ""}) != []


def test_verifier_passes_good_answer():
    r = answer("LED lamp self-ballasted general lighting 9W B22")
    assert not r["refused"] and r["citations"]
    assert verifier.verify(r, retrieve("led lamp")["section_refs"]) == []


def test_matlab_does_not_trigger_lab_journey():
    r = answer("QCO ka matlab simple shabdon me samjhayen")
    assert "lims.bis.gov.in" not in r["text"]


def test_glossary_with_example_is_passes_verifier():
    r = answer("What is an Indian Standard?")
    assert r["kind"] == "glossary"
    assert verifier.verify(r, retrieve("indian standard")["section_refs"]) == []


def test_verifier_fault_injection_all_trips():
    bad = [
        {"text": "Your product is covered by IS 1234.", "citations": [], "refused": False},
        {"text": "See IS 10500 clause 3.1.", "citations": ["IS 10500:2012 — W [Active] — S"],
         "refused": False},
        {"text": "IS 269 applies.", "citations": ["IS 1786:2008 — S [Active] — U"],
         "refused": False},
    ]
    assert all(verifier.verify(b, {}) for b in bad)


def test_thresholds_from_config(monkeypatch):
    import bis_assistant.assistant as A
    monkeypatch.setenv("BIS_RETRIEVAL_DIRECT_SCORE", "1000")
    r = A.answer("vacuum insulated stainless steel water bottle flask 1 litre")
    assert r.get("needs_info") or r.get("refused") or "IS 17803" in r["text"]
    monkeypatch.delenv("BIS_RETRIEVAL_DIRECT_SCORE")
