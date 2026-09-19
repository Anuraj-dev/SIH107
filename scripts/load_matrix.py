"""Load matrix (Phase 8): sustained concurrent /chat requests.

Usage: PYTHONPATH=src BIS_OPS_DB=/tmp/load.db python scripts/load_matrix.py [--n 200] [--c 20]
Reference env per plan: single instance. Asserts successful-response p95 <2000ms.
"""
from __future__ import annotations
import statistics
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

QUERIES = ["steel bottle", "LED bulb CRS registration?", "HUID verify?", "cement OPC grade?",
           "What is a QCO?", "नल के पानी का मानक?", "IS 694 voltage grade?"]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--c", type=int, default=20)
    args = ap.parse_args()
    import os
    os.environ["BIS_OPS_DB"] = str(Path(tempfile.mkdtemp()) / "ops.db")
    import bis_assistant.server as srv
    from fastapi.testclient import TestClient
    with TestClient(srv.app) as client:
        lat, codes = [], {}
        import time

        def one(i: int):
            t0 = time.time()
            r = client.post("/chat", json={"query": QUERIES[i % len(QUERIES)]})
            return r.status_code, (time.time() - t0) * 1000

        with ThreadPoolExecutor(max_workers=args.c) as ex:
            for code, dt in ex.map(one, range(args.n)):
                codes[code] = codes.get(code, 0) + 1
                if code == 200:
                    lat.append(dt)
    lat.sort()
    p50 = lat[len(lat) // 2] if lat else -1
    p95 = lat[int(len(lat) * 0.95)] if lat else -1
    print(f"n={args.n} c={args.c} successful={len(lat)} p50={p50:.0f}ms p95={p95:.0f}ms codes={codes}")
    if not lat or p95 > 2000:
        print("FAIL: no admitted traffic or p95 above 2000ms SLO")
        sys.exit(1)
    print("PASS: p95 within SLO")


if __name__ == "__main__":
    main()
