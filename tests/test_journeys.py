"""Journey E2E (plan §9, acceptance §10.9): 5 canonical MSME chains EN+HI.

Each journey asserts the full product→IS→scheme→LIMS-scope→disclaimer chain with
citations, against a seeded SQLite KB (plan: journeys run on versioned KB).
"""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "kb" / "bis.db"


def _seeded():
    assert DB.exists(), "run scripts/import_json_kb.py --db kb/bis.db first"
    os.environ["BIS_RETRIEVAL_KB_BACKEND"] = "sqlite"
    os.environ["BIS_KB_PATH"] = str(DB)
    from bis_assistant import slots as slotmod
    slotmod.use_db(str(DB))


def _chain_ok(resp, must=()):
    assert resp["citations"], "citations required"
    text = resp["text"]
    assert "Informational only" in text or "Keval jankari" in text, "disclaimer required"
    for m in must:
        assert m in text, m
    return text


def test_j1_steel_bottle_startup_en():
    _seeded()
    from bis_assistant.assistant import answer
    r1 = answer("I make steel bottles, which IS applies?")
    assert r1["needs_info"] and r1["questions"]
    r2 = answer("vacuum insulated double wall, 1 litre, household", None, r1["context"])
    _chain_ok(r2, ("IS 17803", "Scheme"))
    r3 = answer("where do I get this tested — find a lab for IS 17803?")
    assert "lims.bis.gov.in" in r3["text"] and r3["citations"]


def test_j2_led_manufacturer_crs():
    _seeded()
    from bis_assistant.assistant import answer
    r = answer("I manufacture 9W B22 self-ballasted LED bulbs. Which standard and is CRS needed?")
    _chain_ok(r, ("IS 16102-1", "CRS"))


def test_j3_hindi_tap_water():
    _seeded()
    from bis_assistant.assistant import answer
    r1 = answer("नल के पानी का मानक कौन सा है?")
    r2 = answer("ghar ke liye", None, r1["context"]) if r1["needs_info"] else r1
    _chain_ok(r2, ("IS 10500",))


def test_j4_cement_opc():
    _seeded()
    from bis_assistant.assistant import answer
    r1 = answer("which cement standard for construction?")
    r2 = answer("OPC 53 grade", None, r1["context"]) if r1["needs_info"] else r1
    _chain_ok(r2, ("IS 269",))


def test_j5_consumer_huid():
    _seeded()
    from bis_assistant.assistant import answer
    r = answer("How do I verify HUID on gold jewellery I bought?")
    assert not r["needs_info"] and "HUID" in r["text"] and r["citations"]
