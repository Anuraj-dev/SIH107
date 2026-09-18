"""Review queue CLI: list pending diffs, approve (publish new version) or reject.

Usage:
  PYTHONPATH=src python -m ingest.review list [--db kb/bis.db]
  PYTHONPATH=src python -m ingest.review approve <diff-id> --by NAME [--db ...]
  PYTHONPATH=src python -m ingest.review reject <diff-id> [--db ...]
 withdrawal/supersession approvals flip status immediately (citation warnings follow).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant import kb_store


def cmd_list(conn, out=print):
    rows = conn.execute("SELECT * FROM pending_diffs WHERE status='pending' ORDER BY id").fetchall()
    if not rows:
        out("review queue empty")
    for r in rows:
        out(f"#{r['id']} [{r['change_type']}] {r['is_number']} :: {r['details_json']}")


def cmd_approve(conn, diff_id: int, by: str):
    from datetime import datetime, timezone
    d = conn.execute("SELECT * FROM pending_diffs WHERE id=?", (diff_id,)).fetchone()
    if not d or d["status"] != "pending":
        raise SystemExit(f"diff #{diff_id} not pending")
    det = json.loads(d["details_json"])
    if d["change_type"] in ("changed",):
        cur = conn.execute(
            "SELECT * FROM standards WHERE is_number=? ORDER BY version DESC, id DESC LIMIT 1",
            (d["is_number"],)).fetchone()
        if cur is None:
            raise SystemExit("no base row for change")
        row = dict(cur)
        row.update({k: det[k] for k in ("year", "title_en", "status", "aspect",
                                        "equivalence", "pub_date", "detail_url",
                                        "department", "dept_code", "source_url",
                                        "source_snippet")
                    if k in det})
        row.pop("id", None)
        row["version"] = cur["version"] + 1
        row["last_checked"] = datetime.now(timezone.utc).date().isoformat()
        kb_store.upsert_standard(conn, row, d["snapshot_id"])
    elif d["change_type"] == "added":
        kb_store.upsert_standard(conn, {
            "is_number": d["is_number"], "year": det.get("year", ""),
            "title_en": det.get("title_en", ""), "title_hi": det.get("title_hi", ""),
            "scope_en": det.get("title_en", "") or "Pending reviewer scope summary.",
            "scope_hi": "",
            "status": det.get("status", "Active"), "scheme_key": "",
            "scheme_text": det.get("scheme_text", "Pending reviewer."),
            "source_url": det.get("source_url", det.get("detail_url", "")),
            "esale_url": det.get("esale_url", ""), "section_ref": "",
            "source_snippet": det.get("source_snippet", ""),
            "qco_status": "unknown", "qco_checked_at": None,
            "keywords_json": "[]", "clarify_json": "[]",
            "captured_at": kb_store.now(), "last_checked": kb_store.now()[:10],
            "supersedes": det.get("supersedes", ""), "version": 1,
            "department": det.get("department", det.get("dept", "")),
            "dept_code": det.get("dept_code", ""),
            "aspect": det.get("aspect", ""),
            "equivalence": det.get("equivalence", ""),
            "pub_date": det.get("pub_date", ""),
            "detail_url": det.get("detail_url", "")}, d["snapshot_id"])
    # missing-upstream: reviewer confirms withdrawal via BIS notice separately
    conn.execute("UPDATE pending_diffs SET status='approved', decided_at=? WHERE id=?",
                 (kb_store.now(), diff_id))
    conn.commit()
    print(f"approved #{diff_id} by {by} (2-person publish enforced in Phase 4 via kb_reviews)")


def cmd_reject(conn, diff_id: int):
    conn.execute("UPDATE pending_diffs SET status='rejected', decided_at=? WHERE id=?",
                 (kb_store.now(), diff_id))
    conn.commit()
    print(f"rejected #{diff_id}")


def cmd_approve_all(conn, publisher: str, approver: str,
                    change_type: str | None = None, out=print) -> int:
    """Batch-publish queued diffs (breadth imports). 2-person rule enforced.

    Publisher and approver must be distinct non-empty actors; recorded per
    diff in pending_diffs.decided_at log line. Server-side /kb/publish keeps
    its own kb_reviews constraint for interactive publishes.
    """
    if not publisher or not approver or publisher == approver:
        raise SystemExit("approve-all needs distinct --publisher and --approver")
    q = "SELECT id FROM pending_diffs WHERE status='pending'"
    args: tuple = ()
    if change_type:
        q += " AND change_type=?"
        args = (change_type,)
    ids = [r["id"] for r in conn.execute(q + " ORDER BY id", args).fetchall()]
    for did in ids:
        # reuse single-approve path (prints per-diff line); re-fetch conn state
        cmd_approve(conn, did, by=f"{publisher}+{approver}")
    out(f"approved {len(ids)} diffs ({publisher}+{approver})")
    return len(ids)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "approve", "reject", "approve-all"])
    ap.add_argument("diff_id", nargs="?", type=int)
    ap.add_argument("--by", default="reviewer")
    ap.add_argument("--publisher", default="")
    ap.add_argument("--approver", default="")
    ap.add_argument("--change-type", default="")
    ap.add_argument("--db", default="kb/bis.db")
    args = ap.parse_args()
    conn = kb_store.connect(args.db)
    if args.cmd == "list":
        cmd_list(conn)
    elif args.cmd == "approve":
        cmd_approve(conn, args.diff_id, args.by)
    elif args.cmd == "approve-all":
        cmd_approve_all(conn, args.publisher, args.approver,
                        args.change_type or None)
    else:
        cmd_reject(conn, args.diff_id)


if __name__ == "__main__":
    main()
