"""Load smoke (Phase 3 exit; full k6/Locust matrix in Phase 8).

Usage: PYTHONPATH=src BIS_OPS_DB=/tmp/smoke.db python scripts/load_smoke.py [--n 100] [--c 10]
Spins the FastAPI app in-process (TestClient) and reports p50/p95 + status mix.
"""
from __future__ import annotations
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

QUERIES = ["steel bottle", "LED bulb CRS?", "HUID verify?", "cement grade?",
           "What is a QCO?", "नल के पानी का मानक?"]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--c", type=int, default=10)
    args = ap.parse_args()
    import os
    tmp = tempfile.mkdtemp()
    os.environ["BIS_OPS_DB"] = str(Path(tmp) / "ops.db")
    import bis_assistant.server as srv
    from fastapi.testclient import TestClient
    lat, codes = [], {}
    with TestClient(srv.app) as client:
        def one(i: int):
            t0 = time.time()
            r = client.post("/chat", json={"query": QUERIES[i % len(QUERIES)]})
            dt = (time.time() - t0) * 1000
            return r.status_code, dt
        with ThreadPoolExecutor(max_workers=args.c) as ex:
            for code, dt in ex.map(one, range(args.n)):
                codes[code] = codes.get(code, 0) + 1
                lat.append(dt)
    lat.sort()
    p50 = lat[len(lat) // 2]
    p95 = lat[int(len(lat) * 0.95)]
    print(f"n={args.n} c={args.c} p50={p50:.0f}ms p95={p95:.0f}ms codes={codes}")
    ok = codes.get(200, 0) / args.n
    print(f"2xx rate: {ok:.1%} (429s expected past burst caps)")
    if p95 > 2000:
        print("WARN: p95 above 2000ms SLO")
        sys.exit(1)


if __name__ == "__main__":
    main()
