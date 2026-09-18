"""Retention purge (Phase 4): expired threads/messages, over-retention rows, stale audit.

Usage: PYTHONPATH=src python scripts/purge.py [--db kb/ops.db] [--dry-run]
Exit 0 always on success; prints counts. Wire to cron weekly in pilot.
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bis_assistant.config import load as load_config


def purge(db: str, dry_run: bool = False) -> dict:
    import bis_assistant.server as srv
    srv.DB_PATH = Path(db)
    conn = srv._db()
    try:
        cfg = load_config()["privacy"]
        now = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg["retention_days"])).isoformat()
        counts = {}
        counts["expired_threads"] = conn.execute(
            "SELECT COUNT(*) c FROM threads WHERE expires_at < ?", (now,)).fetchone()["c"]
        counts["old_messages"] = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE created_at < ?", (cutoff,)).fetchone()["c"]
        if not dry_run:
            tids = [r["id"] for r in conn.execute(
                "SELECT id FROM threads WHERE expires_at < ?", (now,)).fetchall()]
            for tid in tids:
                conn.execute("DELETE FROM messages WHERE thread_id=?", (tid,))
            conn.execute("DELETE FROM threads WHERE expires_at < ?", (now,))
            conn.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
            conn.commit()
        return counts
    finally:
        conn.close()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="kb/ops.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(purge(args.db, args.dry_run))


if __name__ == "__main__":
    main()
