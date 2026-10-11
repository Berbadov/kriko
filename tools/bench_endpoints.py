"""Latency of the reader-facing endpoints against a store with real packs.

Starts one sidecar in a throwaway HOME (see `bench_startup.py`), with a copy
of the store given by `--store`, then sends each request `--requests` times
over one keep-alive connection and reports p50 and p95 in milliseconds:

    python tools/bench_endpoints.py --store path/to/knowledge.sqlite

Build and install packs with the repo's own builder first (docs/USAGE.md):
`python -m app.cli build packs/<name> --out X.kpack`, then
`python -m app.cli --store STORE install X.kpack`.
"""

import argparse
import http.client
import json
import statistics
import sys
import tempfile
import shutil
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_startup import REPO, launch, read_port  # noqa: E402

LOOKUP_BODY = {
    "kind": "product",
    "identity": {
        "make": "renault", "model": "clio", "engine_code": "H4D", "fuel": "petrol",
        "displacement_cc": "999", "transmission_code": "manual", "power_min_hp": "75",
    },
    "context": {},
    "lang": "en",
    "limit": 8,
}

REQUESTS = [
    ("GET", "/api/health", None),
    ("GET", "/api/adapters", None),
    ("POST", "/api/lookup", LOOKUP_BODY),
    ("GET", "/api/search?q=clio&limit=20", None),
]


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def time_one(conn: http.client.HTTPConnection, method: str, path: str, body) -> tuple[float, int]:
    payload = None if body is None else json.dumps(body).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    started = time.perf_counter()
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    response.read()
    return (time.perf_counter() - started) * 1000, response.status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--repo", type=Path, default=REPO,
                        help="checkout whose src/ runs (default: this one)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="kriko-bench-") as tmp:
        home = Path(tmp)
        target = home / ".kriko" / "knowledge.sqlite"
        target.parent.mkdir(parents=True)
        shutil.copy(args.store, target)
        proc = launch(args.python, home, target, args.repo)
        try:
            port = read_port(proc, timeout=120)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            for _ in range(50):
                try:
                    if time_one(conn, "GET", "/api/health", None)[1] == 200:
                        break
                except OSError:
                    conn.close()
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                time.sleep(0.05)
            results = {}
            for method, path, body in REQUESTS:
                # Warm-up outside the sample: the first call of each route pays
                # for lazily built caches, which is not what a reader repeats.
                time_one(conn, method, path, body)
                samples, statuses = [], set()
                for _ in range(args.requests):
                    elapsed, status = time_one(conn, method, path, body)
                    samples.append(elapsed)
                    statuses.add(status)
                results[f"{method} {path}"] = {
                    "p50_ms": round(percentile(samples, 0.50), 2),
                    "p95_ms": round(percentile(samples, 0.95), 2),
                    "median_ms": round(statistics.median(samples), 2),
                    "statuses": sorted(statuses),
                    "n": len(samples),
                }
            conn.close()
        finally:
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
                proc.wait()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for name, stats in results.items():
            print(f"{name:34s} p50 {stats['p50_ms']:8.2f} ms  p95 {stats['p95_ms']:8.2f} ms"
                  f"  statuses {stats['statuses']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
