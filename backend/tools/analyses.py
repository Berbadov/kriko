"""CLI read path for logs/analyses.jsonl — no DB client, no browser needed.

docs/design_flaws.md "Observability gap": the only way to see what /analyze
served used to be opening the DB by hand and joining claim IDs back to titles.
This reads the full-payload JSONL log (backend/observability.py) directly.

    python -m backend.tools.analyses --last 20
    python -m backend.tools.analyses --last 20 --model golf
    python -m backend.tools.analyses --last 5 --json      # full records
"""

import argparse
import json

from backend.observability import read_recent


def _format_line(rec: dict) -> str:
    resp  = rec.get("response") or {}
    match = rec.get("match") or {}
    meta  = rec.get("ad_metadata") or {}
    risks = resp.get("risks") or []

    titles = ", ".join(r["title"] for r in risks[:3])
    if len(risks) > 3:
        titles += f", +{len(risks) - 3} more"

    line = (
        f"{rec.get('created_at', '?')}  "
        f"{meta.get('make', '?')} {meta.get('model', '?')} {meta.get('year', '?')}  "
        f"[{resp.get('coverage_state', '?')}] "
        f"match={match.get('method', '?')} variants={match.get('variant_ids') or []}  "
        f"risks={len(risks)}"
    )
    if titles:
        line += f": {titles}"
    if rec.get("error"):
        line += f"  ERROR={rec['error']}"
    line += f"  id={rec.get('id', '?')}"
    return line


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--last", type=int, default=20, help="Number of recent analyses to show")
    parser.add_argument("--model", default=None, help="Filter by model (case-insensitive substring)")
    parser.add_argument("--json", action="store_true", help="Print full JSON records instead of one-line summaries")
    args = parser.parse_args()

    records = read_recent(limit=args.last, model=args.model)
    if not records:
        print("No analyses logged yet (check ANALYSES_LOG_PATH).")
        return

    for rec in records:
        print(json.dumps(rec, indent=2) if args.json else _format_line(rec))


if __name__ == "__main__":
    main()
