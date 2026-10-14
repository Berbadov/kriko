"""Compare cold app-server processes with a resident worker, using fresh threads.

Run with --live to authorize small inference calls on the selected CLI account.
Both sides use identical isolated configuration; this measures transport reuse,
not research quality or a comparison against the legacy exec tool configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.providers import codex_profile  # noqa: E402
from app.providers.codex_transport import CodexRequest, CodexTransport  # noqa: E402
from app.version import app_version  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="low")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this benchmark sends inference requests")
    if not 1 <= args.samples <= 20:
        parser.error("--samples must be between 1 and 20")
    executable = shutil.which("codex")
    if executable is None:
        parser.error("Codex is not installed")
    source_digest = hashlib.sha256()
    for name in ("src/app/providers/codex_transport.py", "src/app/providers/codex_profile.py",
                 "src/app/processcontrol.py", "src/app/agentresources.py"):
        source_digest.update(name.encode())
        source_digest.update((ROOT / name).read_bytes())
    report = {
        "date": datetime.now(UTC).isoformat(), "platform": platform.platform(),
        "python": platform.python_version(), "kriko_version": app_version(),
        "cli_version": subprocess.run([executable, "--version"], capture_output=True,
                                      text=True, timeout=10).stdout.strip(),
        "implementation_sha256": source_digest.hexdigest(),
        "model": args.model, "effort": args.effort, "samples_per_mode": args.samples,
        "notes": "Identical tool-less profiles; fresh thread each call. Warm-up recorded separately. "
                 "Provider caching and network/generation vary; no research-quality claim.",
        "results": [],
    }
    profile = codex_profile.profile(executable, model=args.model, effort=args.effort,
                                   namespace="paired-transport-benchmark")
    request = CodexRequest("Reply with exactly READY. Do not use tools.", {}, timeout=args.timeout)
    warm = CodexTransport()

    def measure(owner, mode, index):
        began = time.monotonic()
        try:
            result = owner.run(profile, request)
            item = {"mode": mode, "index": index,
                    "seconds": round(time.monotonic() - began, 6), "ready": result.text.strip() == "READY",
                    "reuse_valid": bool(result.metrics.get("reused_worker")) == (mode == "warm"),
                    "thread_id": result.thread_id, "turn_id": result.turn_id,
                    "usage": dict(result.usage), "metrics": dict(result.metrics)}
        except Exception as error:
            item = {"mode": mode, "index": index,
                    "seconds": round(time.monotonic() - began, 6), "ready": False,
                    "error_type": type(error).__name__}
        report["results"].append(item)
        print(json.dumps(item), flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    try:
        measure(warm, "warm_up", 0)
        for index in range(args.samples):
            # Alternate the pair order to avoid always giving the warm side
            # the later cache/network conditions.
            for mode in (("cold", "warm") if index % 2 == 0 else ("warm", "cold")):
                if mode == "warm":
                    measure(warm, mode, index)
                else:
                    cold = CodexTransport()
                    try:
                        measure(cold, mode, index)
                    finally:
                        cold.close()
    finally:
        warm.close()
        codex_profile.shutdown()
    report["summary"] = {}
    for mode in ("cold", "warm"):
        values = [row["seconds"] for row in report["results"] if row["mode"] == mode and row["ready"]]
        report["summary"][mode] = {
            "completed": len(values), "failed": args.samples - len(values),
            "median_seconds": statistics.median(values) if values else None,
        }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(row["ready"] and row.get("reuse_valid", False) for row in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
