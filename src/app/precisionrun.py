"""Run local configuration measurements into an isolated, inspectable report.

``python -m app.precisionrun --model <installed-name> --output <directory>``
No web requests, no paid API, and no writes to the reader's own history.
"""

import argparse
import json
from pathlib import Path

from app import bench, benchcases, prefs, protocols
from app.web import state
from app.web.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=None, help="Limit cases; the default runs the entire suite")
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.reps <= 10:
        parser.error("--reps must be between 1 and 10")
    if args.cases is not None and args.cases < 1:
        parser.error("--cases must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    settings = Settings(store_path=args.output / "knowledge.sqlite",
                        app_state_path=args.output / "app.sqlite",
                        analysis_log_path=args.output / "analyses.jsonl")
    conn = state.connect(settings.app_state_path)
    rows = []
    try:
        state.put_settings(conn, {prefs.LOCAL_URL: args.base_url})
        for model in args.model:
            for rep in range(1, args.reps + 1):
                for case in benchcases.case_rows(args.cases or len(benchcases.load())):
                    row = bench.run_case(settings, case, plane="local", model=model,
                                         batch_id="configuration-experiment")
                    row["rep"] = rep
                    state.record_bench(conn, row)
                    rows.append(row)
                    score = row.get("gold") or {}
                    print(f"{model} rep {rep} {case['id']}: "
                          f"{'FAIL: ' + row['error'] if row.get('error') else 'pass=' + str(score.get('pass'))} "
                          f"{row.get('ms', 0) / 1000:.2f}s {row.get('tokens')} tokens", flush=True)
                    report = {"set_id": benchcases.SET_ID, "set_version": benchcases.SET_VERSION,
                              "synthetic": True, "rows": rows,
                              "readout": protocols.readout(rows, [])}
                    pending = args.output / "results.pending.json"
                    pending.write_text(
                        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    pending.replace(args.output / "results.json")
    finally:
        conn.close()
    return int(all(row.get("error") for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
