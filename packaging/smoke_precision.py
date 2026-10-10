"""Run the configuration benchmark through a frozen engine's HTTP job API.

    python packaging/smoke_precision.py path/to/kriko-sidecar.exe --model INSTALLED --output REPORT_DIR

Uses only the named local model and a separate store. Model accuracy failures
remain visible in the report; broken jobs or missing measurements fail this check.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from smoke_sidecar import end, fetch


def send(port: int, path: str, body: dict, method: str = "POST") -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cases", type=int, choices=range(1, 10), default=9)
    args = parser.parse_args()
    binary, output = args.binary.resolve(), args.output.resolve()
    if not binary.is_file():
        parser.error(f"missing frozen engine: {binary}")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "app.sqlite").exists():
        parser.error("use a fresh output directory so earlier results cannot make this pass")
    environment = os.environ | {
        "KRIKO_STORE": str(output / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(output / "app.sqlite"),
        "KRIKO_ANALYSES_LOG": str(output / "analyses.jsonl"),
        "KRIKO_LOG": str(output / "engine.log"),
    }
    with (output / "engine-stderr.txt").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [str(binary), "--port", "0", "--extension-port", "0"],
            stdout=subprocess.PIPE, stderr=errors, text=True, env=environment,
        )
        reader = ThreadPoolExecutor(max_workers=1)
        try:
            line = reader.submit(process.stdout.readline).result(timeout=60).strip()
            assert line.startswith("KRIKO_PORT "), f"missing handshake: {line!r}"
            port = int(line.split()[1])
            deadline = time.monotonic() + 60
            while True:
                try:
                    health = fetch(port, "/api/health")
                    break
                except (OSError, TimeoutError):
                    assert time.monotonic() < deadline, "engine never became ready"
                    time.sleep(0.2)
            send(port, "/api/prefs", {"local_url": args.base_url,
                                      "local_model": args.model}, "PUT")
            body = {"suite": "precision", "planes": "local", "llms": args.model,
                    "cases": args.cases, "reps": 1, "budget_usd": 0}
            estimate = send(port, "/api/bench/estimate", body)
            started = send(port, "/api/bench", body)
            deadline = time.monotonic() + 600
            while True:
                job = fetch(port, f"/api/jobs/{started['job_id']}")
                if job.get("done"):
                    break
                assert time.monotonic() < deadline, "benchmark job did not finish"
                time.sleep(0.5)
            served = fetch(port, "/api/bench")
            report = {"binary": str(binary), "health": health, "request": body,
                      "estimate": estimate, "job": job, "bench": served}
            (output / "results.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            assert job.get("state") == "succeeded", f"benchmark failed: {job.get('message')}"
            rows = served["runs"]
            assert len(rows) == args.cases, f"expected {args.cases} rows, got {len(rows)}"
            assert all(not row.get("error") for row in rows), "a measurement failed"
            assert all(row["measurement"].get("usage_complete") is True and row.get("tokens", 0) > 0
                       and row["measurement"].get("tokens_in", 0) > 0
                       and row["measurement"].get("tokens_out", 0) > 0
                       for row in rows), "missing token accounting"
            assert all(row.get("gold") and row["measurement"].get("stages") and row.get("bench_id")
                       and row.get("protocol") == "local-extractive-v2"
                       for row in rows), "missing grade, stages, identity or protocol"
            assert served["readout"], "native screen has no readout to display"
            for row in rows:
                usage = row["measurement"]
                print(f"{row['subject_id']}: pass={row['gold'].get('pass')}; "
                      f"{row['ms']}ms; {usage['tokens_in']} input/{usage['tokens_out']} output tokens")
            print(f"frozen configuration journey ok: {len(rows)} saved, scored measurements")
            return 0
        finally:
            end(process)
            reader.shutdown(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())
