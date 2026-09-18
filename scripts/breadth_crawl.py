"""Breadth crawl: DG-dashboard lists (+ CRS QCO seed) into the versioned KB.

Metadata only (decisions #2/#3). Respects crawl-delay, session reuse, the
host allowlist + robots/ToS gate (e-sale/manakonline raise, never fetched).

Usage:
  PYTHONPATH=src python scripts/breadth_crawl.py --dry-run
  PYTHONPATH=src python scripts/breadth_crawl.py --dept AYD --max-pages 1 --dry-run
  PYTHONPATH=src python scripts/breadth_crawl.py --queue
  PYTHONPATH=src python scripts/breadth_crawl.py --queue --publish \\
      --publisher NAME --approver OTHER-NAME
  PYTHONPATH=src python scripts/breadth_crawl.py --report [--db kb/bis.db]

--dry-run fetches and parses but writes nothing (proves the feed works).
--queue stores raw snapshots + queues added/changed diffs for human review.
--publish batch-approves the queued diffs; needs two DISTINCT humans.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bis_assistant import kb_store  # noqa: E402
from ingest import breadth as B  # noqa: E402
from ingest import review as reviewmod  # noqa: E402
from ingest import snapshot as snapmod  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "kb" / "breadth_raw"  # local checkpoints (gitignored), resumable


def _save_checkpoint(code: str, payload: dict) -> None:
    import json
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{code}.json").write_text(json.dumps(payload, ensure_ascii=False))


def _load_checkpoint(code: str) -> dict | None:
    import json
    p = RAW_DIR / f"{code}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def cmd_report(db: str) -> None:
    conn = kb_store.connect(db)
    try:
        pub = conn.execute("SELECT COUNT(*) c FROM standards").fetchone()["c"]
        pend = conn.execute("SELECT change_type, COUNT(*) c FROM pending_diffs"
                            " WHERE status='pending' GROUP BY 1").fetchall()
        pend_map = {r["change_type"]: r["c"] for r in pend}
        print(f"KB {db}: published standards={pub}"
              f" pending={dict(pend_map)}")
        print("Live total (DG dashboard, VERIFIED 2026-09-18): 22471")
        if pub:
            print(f"Published coverage: {100*pub/22471:.2f}%")
    finally:
        conn.close()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="kb/bis.db")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--length", type=int, default=500)
    ap.add_argument("--dept", default="",
                    help="dept_code prefix to limit crawl (e.g. AYD)")
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--skip-crs", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--queue", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="reuse per-dept checkpoints in kb/breadth_raw/")
    ap.add_argument("--publisher", default="")
    ap.add_argument("--approver", default="")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.report:
        cmd_report(args.db)
        return
    if not (args.dry_run or args.queue):
        ap.error("choose --dry-run, --queue, or --report")
    if args.publish and not args.queue:
        ap.error("--publish needs --queue")
    if args.publish and (not args.publisher or args.publisher == args.approver):
        ap.error("--publish needs distinct --publisher and --approver")

    today = date.today().isoformat()
    crawler = B.DGCrawler(delay_s=args.delay)
    main_html = crawler.get(B.DG_MAIN)
    depts = B.parse_dgdept_table(main_html)
    if args.dept:
        depts = [d for d in depts
                 if d.get("dept_code", "").upper().startswith(args.dept.upper())]
        if not depts:
            raise SystemExit(f"no department matches {args.dept!r}")
    live_total = sum(d["total"] for d in B.parse_dgdept_table(main_html))
    print(f"departments: {len(depts)} live_total={live_total}")

    all_records: list[dict] = []
    for d in depts:
        code = d.get("dept_code") or "UNKNOWN"
        if args.resume and not args.dry_run:
            cp = _load_checkpoint(code)
            if cp and cp.get("expected") and len(cp.get("records", [])) >= cp["expected"]:
                print(f"  {code}: resumed from checkpoint ({len(cp['records'])} records)",
                      flush=True)
                all_records.extend(cp["records"])
                continue
        recs = crawler.crawl_department(
            d, length=args.length, max_pages=args.max_pages,
            progress=lambda c, n, e: print(f"  {c}: {n}/{e}", flush=True))
        print(f"  {d['dept_code']}: listed={d['total']} fetched={len(recs)}", flush=True)
        if not args.dry_run:
            _save_checkpoint(code, {"dept": d, "expected": d["total"],
                                    "records": recs})
        all_records.extend(recs)

    crs_rows: list[dict] = []
    if not args.skip_crs:
        crs_html = crawler.get(B.CRS_PRODUCTS)
        crs_rows = B.parse_crs_table(crs_html)
        print(f"  CRS products-bis.do: {len(crs_rows)} rows", flush=True)
        if not args.dry_run:
            _save_checkpoint("CRS", {"records": crs_rows})

    if args.dry_run:
        print(f"DRY RUN: {len(all_records)} breadth records, "
              f"{len(crs_rows)} CRS rows (nothing written)")
        return

    conn = kb_store.connect(args.db)
    try:
        snap = kb_store.new_snapshot(
            conn, "breadth_crawl",
            f"DG dashboard ({len(depts)} depts) + CRS ({len(crs_rows)} rows)")
        conn.execute("CREATE TABLE IF NOT EXISTS raw_pages"
                     "(snapshot_id INTEGER, url TEXT, raw TEXT)")
        conn.execute("INSERT INTO raw_pages VALUES (?,?,?)",
                     (snap, B.DG_MAIN, main_html[:200000]))
        conn.commit()
        stats = snapmod.queue_breadth_records(conn, snap, all_records)
        print(f"queued into {args.db} (snapshot {snap}): {stats}")
        # CRS rows are reviewer evidence, not auto-published QCO flags.
        if crs_rows:
            conn.execute("INSERT INTO raw_pages VALUES (?,?,?)",
                         (snap, B.CRS_PRODUCTS,
                          "\n".join(f"{r['product']} | {r['is_raw']} | "
                                    f"{r['qco_date']}" for r in crs_rows)))
            conn.commit()
        if args.publish:
            n = reviewmod.cmd_approve_all(conn, args.publisher,
                                          args.approver, "added")
            print(f"published {n} breadth rows (2-person: "
                  f"{args.publisher}+{args.approver})")
        cmd_report(args.db)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
