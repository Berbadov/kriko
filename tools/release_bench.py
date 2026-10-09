"""Measure the shipped fixed research cases without changing user knowledge.

Run from the repository root with its virtualenv. Credential files are read
only when explicitly supplied and keys are never included in the output.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import bench, benchcases, machine  # noqa: E402
from app.version import app_version  # noqa: E402
from app.web.settings import Settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--plane", choices=["harness", "local", "api"], required=True)
    parser.add_argument("--harness", default="")
    parser.add_argument("--cases", type=int, default=3)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--budget", type=float, default=0.20)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--mistral-key-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mistral_key_file:
        key = args.mistral_key_file.read_text(encoding="utf-8").strip()
        if "=" in key:
            key = key.split("=", 1)[1].strip().strip("\"'")
        os.environ["MISTRAL_API_KEY"] = key
    started = datetime.now(timezone.utc).isoformat()
    metadata = {
        "app_version": app_version(),
        "label": args.label, "requested_model": args.model,
        "harness": args.harness, "plane": args.plane,
        "started_at": started, "platform": platform.platform(),
        "python": platform.python_version(), "gpu": machine._smi(),
        "limits": {"pages": args.pages, "budget_usd": args.budget,
                   "timeout_seconds": args.timeout},
        "set_id": benchcases.SET_ID, "set_version": benchcases.SET_VERSION,
    }
    source_root = Path(__file__).resolve().parents[1] / "src"
    metadata["code_sha256"] = {
        name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
        for name in ("app/bench.py", "app/providers/__init__.py",
                     "app/providers/apiagent.py", "app/providers/local_agent.py")
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kriko-release-bench-") as folder:
        sandbox = Path(folder)
        settings = replace(Settings(), store_path=sandbox / "knowledge.sqlite",
                           app_state_path=sandbox / "app.sqlite",
                           analysis_log_path=sandbox / "analysis.jsonl")
        bench._copy_settings(Settings().app_state_path, settings.app_state_path)
        with args.output.open("w", encoding="utf-8") as output:
            for case in benchcases.case_rows(args.cases):
                print(f"START {args.label}: {case['id']}", flush=True)
                row = bench.run_case(
                    settings, case, plane=args.plane, model=args.model,
                    max_documents=args.pages, budget_usd=args.budget,
                    batch_id="release-" + started,
                    run_settings={"harness": args.harness,
                                  "timeout_seconds": args.timeout,
                                  "temperature": 0, "max_tokens": 1024},
                )
                # Publish evidence references, not copies of third-party pages.
                detail = row.get("detail") or {}
                sources = detail.get("sources") or {}
                detail["sources"] = {
                    url: {"characters": len(text),
                          "sha256": hashlib.sha256(text.encode()).hexdigest()}
                    for url, text in sources.items() if isinstance(text, str)
                }
                record = {"measurement": metadata, "result": row}
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                print(json.dumps({"case": case["id"], "ms": row.get("ms"),
                                  "model": row.get("model"),
                                  "accepted": row.get("accepted"),
                                  "error": row.get("error", "")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
