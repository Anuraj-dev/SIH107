"""Import flat JSON KB (+ slots.py + journey URLs) into SQLite as snapshot v1.

Usage: PYTHONPATH=src python scripts/import_json_kb.py [--db kb/bis.db] [--note TEXT]
Idempotent for fresh DBs; refuses to double-import the same source snapshot.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant import kb_store
from bis_assistant import slots as slotmod

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TODAY = "2026-09-18"

INFO_PAGES = [  # seeds from currently hardcoded assistant URLs (plan §2)
    ("hallmarking", "BIS Hallmarking overview",
     "https://www.bis.gov.in/hallmarking-overview/"),
    ("lims", "BIS LIMS IS-wise facility",
     "https://lims.bis.gov.in/home/search_is_number/"),
    ("training", "BIS training programmes",
     "https://www.bis.gov.in/training-2/training-programmes/"),
]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="kb/bis.db")
    ap.add_argument("--note", default="v1 import from data/*.json")
    args = ap.parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = kb_store.connect(db)
    if conn.execute("SELECT COUNT(*) c FROM standards").fetchone()["c"]:
        print(f"{db} already populated; refusing double import")
        return
    stds = json.loads((DATA / "standards.json").read_text())
    schemes = json.loads((DATA / "schemes.json").read_text())
    labs = json.loads((DATA / "labs.json").read_text())
    gloss = json.loads((DATA / "glossary.json").read_text())
    snap = kb_store.new_snapshot(conn, "import_json_kb", args.note)
    for s in stds["standards"]:
        kb_store.upsert_standard(conn, {
            "is_number": s["is_number"], "year": s.get("year", ""),
            "title_en": s.get("title_en", ""), "title_hi": s.get("title_hi", ""),
            "scope_en": s.get("scope_en", ""), "scope_hi": s.get("scope_hi", ""),
            "status": s.get("status", "Active"), "scheme_key": "",
            "scheme_text": s.get("scheme", ""), "source_url": s.get("source_url", ""),
            "esale_url": stds.get("esale_base", ""), "section_ref": "",
            "source_snippet": "", "qco_status": "unknown", "qco_checked_at": None,
            "keywords_json": json.dumps(s.get("category_keywords", [])),
            "clarify_json": json.dumps(s.get("clarify", [])),
            "captured_at": TODAY, "last_checked": s.get("last_checked", TODAY),
            "supersedes": "", "version": 1}, snap)
    for s in schemes["schemes"]:
        conn.execute("INSERT INTO schemes VALUES (?,?,?,?,?,?,?,?,?)",
                     (s["key"], s["name_en"], s["name_hi"],
                      json.dumps(s["process_en"]), json.dumps(s["process_hi"]),
                      s["apply_at"], s["source_url"], s.get("suitable_for", ""),
                      schemes.get("last_checked", TODAY)))
    for lab in labs["samples"]:
        conn.execute("INSERT INTO labs(name,city,type,scope_note,source_url,last_checked,verified)"
                     " VALUES (?,?,?,?,?,?,0)",
                     (lab["name"], lab["city"], lab["type"], lab["scope"],
                      "https://www.bis.gov.in/directory/laboratory/", TODAY))
    for g in gloss["glossary"]:
        conn.execute("INSERT INTO glossary VALUES (?,?,?,?)",
                     (g["term"], g["en"], g["hi"],
                      "https://www.bis.gov.in/know-your-standard"))
    for is_no, slots in slotmod.SLOTS.items():
        for sl in slots:
            conn.execute("INSERT INTO slots VALUES (?,?,?,?,?,?)",
                         (is_no, sl["key"], sl["q_en"], sl["q_hi"],
                          json.dumps(sl.get("options", [])), sl.get("pattern")))
    for key, title, url in INFO_PAGES:
        conn.execute("INSERT INTO info_pages VALUES (?,?,?,?)", (key, title, url, TODAY))
    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM standards").fetchone()["c"]
    print(f"imported {n} standards + schemes/labs/glossary/slots/info_pages -> {db} (snapshot {snap})")


if __name__ == "__main__":
    main()
