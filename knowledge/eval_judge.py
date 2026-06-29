"""eval_judge.py — run gates over the gold set and print accuracy metrics.

Usage:
    ANTHROPIC_API_KEY=... python -m knowledge.eval_judge

Prints precision/recall per gate and highlights which gate is drifting.
"""

import sys
from pathlib import Path

import yaml

from knowledge.judge import gate_generic, gate_support


GOLD_PATH = Path(__file__).parent / "gold" / "gold.yaml"


def run():
    entries = yaml.safe_load(GOLD_PATH.read_text())
    if not entries:
        print("Gold set is empty — add entries to knowledge/gold/gold.yaml")
        sys.exit(0)

    tp = fp = tn = fn = 0
    failures: list[str] = []

    for entry in entries:
        expected_correct = entry["verdict"] == "correct"

        # gate_generic: should PASS (not generic) for correct claims,
        # and FAIL (is generic) for incorrect/generic ones.
        try:
            generic_result = gate_generic(entry["title"], entry["rationale"])
            gate_says_specific = generic_result.passed   # True = NOT generic
        except Exception as exc:
            print(f"  SKIP {entry['claim_key']}: gate_generic error: {exc}")
            continue

        # gate_support: should PASS for correct claims.
        try:
            support_result = gate_support(entry["title"], entry["rationale"], entry["quote"])
            gate_says_supported = support_result.passed
        except Exception as exc:
            print(f"  SKIP {entry['claim_key']}: gate_support error: {exc}")
            continue

        # Combined: claim passes both gates → we call it "correct"
        gate_correct = gate_says_specific and gate_says_supported

        if expected_correct and gate_correct:
            tp += 1
        elif expected_correct and not gate_correct:
            fn += 1
            failures.append(f"  FALSE NEG: {entry['claim_key']} "
                            f"(generic={not gate_says_specific}, supported={gate_says_supported})")
        elif not expected_correct and not gate_correct:
            tn += 1
        else:
            fp += 1
            failures.append(f"  FALSE POS: {entry['claim_key']} "
                            f"(generic={not gate_says_specific}, supported={gate_says_supported})")

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"\nGold set: {total} entries")
    print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    print(f"  Precision: {precision:.2f}  Recall: {recall:.2f}  F1: {f1:.2f}")
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f)
    else:
        print("\nAll gold entries classified correctly.")


if __name__ == "__main__":
    run()
