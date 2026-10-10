"""Regrade stored raw proposals using one answer key, without rerunning models.

Run with PYTHONPATH=src. Input paths are reports from app.precisionrun.
Latency and usage remain historical observations, not controlled speed trials.
"""

import argparse
import copy
import json
from pathlib import Path

from app import benchcases, precisionbench, protocols


def regrade(report):
    cases = {case["id"]: case for case in benchcases.case_rows(50)}
    rows = copy.deepcopy(report["rows"])
    for row in rows:
        case = cases[row["subject_id"]]
        if row["subject"] != case["product"]:
            raise ValueError("product changed between reports; comparison needs manual review")
        previous = row.get("gold") or {}
        if not row.get("error"):
            if "proposed_risks" not in previous or "proposed_specs" not in previous:
                raise ValueError("stored raw proposals are missing; do not compare filtered answers")
            raw = json.dumps({"risks": previous["proposed_risks"],
                              "specs": previous["proposed_specs"]})
            if previous.get("valid_shape") is False:
                raw = "unreadable stored answer"
            row["gold"] = {**previous, **precisionbench.judge(case, raw, {
                doc["url"]: doc["text"] for doc in case["documents"]})}
        row["set_version"] = benchcases.SET_VERSION
        # Early baseline factory failures preceded tagging the controlled
        # search provider. They did not run a different search experiment.
        row["search_provider"] = "supplied-corpus"
    return protocols.readout(rows, [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    result = {
        "method": "Regraded stored raw proposals; no model rerun. Timing and usage unchanged.",
        "answer_key": benchcases.SET_VERSION, "baseline_original_version": baseline["set_version"],
        "baseline_file": str(args.baseline), "current_file": str(args.current),
        "baseline": regrade(baseline), "current": regrade(current),
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
