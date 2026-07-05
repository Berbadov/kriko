"""eval_judge.py — run every quality check over the gold set and print
per-check accuracy metrics.

Usage:
    python -m knowledge.eval_judge   # needs MISTRAL_API_KEY in .env for the LLM gates

Each gold entry declares `expected_issues: [check_name, ...]` — the checks
that SHOULD catch it (empty list for a genuinely correct claim). A check is
scored only against entries where it's actually applicable: entries that
list it (positive case) or entries that don't list it at all (negative
case, regardless of what OTHER issues that entry has — e.g. a claim can have
a bad `dtc_code`-litany title while still being legitimately non-generic
content, so it's still a valid negative test for the `generic` check).

Checks:
  - generic:          gate_generic — is this trivial to any car?
  - support:          gate_support — does the quote support the claim?
  - dtc_code:         title must NOT lead with a raw diagnostic code
  - verbose:          title must be a brief phrase, not a paragraph
  - no_variant_anchor: title must carry an engine/transmission code or
                       displacement+fuel-tech label — "brief" must not mean
                       "generic," CLAUDE.md wants config-SPECIFIC risk
  - cross_brand:      (only when `own_makes`/`expect_flagged` are set) does
                       the guard correctly flag an unrelated-brand mention
                       for LLM scrutiny? Scored against `expect_flagged`,
                       NOT `verdict` — a flagged claim can still turn out
                       correct after gate_variant review (shared-platform
                       parts like the Getrag 7DCT300).

Known gaps this benchmark surfaces but does not yet close (no check exists):
`factually_impossible` (claim contradicts the vehicle's own powertrain/fuel
type) and `non_automotive` (source content isn't even about a car) — see
knowledge/gold/gold.yaml verdict_notes for the specific entries.
"""

import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from knowledge.judge import gate_generic, gate_support
from knowledge.promote import _mentions_other_brand
from knowledge.stoplists import has_variant_anchor, title_has_dtc_code, title_is_verbose

GOLD_PATH = Path(__file__).parent / "gold" / "gold.yaml"

CHECKS = ["generic", "support", "dtc_code", "verbose", "no_variant_anchor", "cross_brand"]


def _claim_text(entry: dict) -> str:
    return " ".join(
        p for p in (entry.get("title"), entry.get("rationale"), entry.get("engine_or_variant_hint")) if p
    )


def _score(bucket: dict, check_says_ok: bool, should_be_ok: bool) -> None:
    if should_be_ok and check_says_ok:
        bucket["tp"] += 1
    elif should_be_ok and not check_says_ok:
        bucket["fn"] += 1
    elif not should_be_ok and not check_says_ok:
        bucket["tn"] += 1
    else:
        bucket["fp"] += 1


def run():
    entries = yaml.safe_load(GOLD_PATH.read_text())
    if not entries:
        print("Gold set is empty — add entries to knowledge/gold/gold.yaml")
        sys.exit(0)

    counts = {c: {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "skipped": 0} for c in CHECKS}

    for entry in entries:
        issues = entry.get("expected_issues")
        title = entry["title"]

        def wanted_ok(check_name: str) -> bool:
            return check_name not in (issues or [])

        # LLM gates — skip (not fail) if no API key.
        try:
            r = gate_generic(entry["title"], entry["rationale"])
            _score(counts["generic"], r.passed, wanted_ok("generic"))
        except Exception as exc:
            print(f"  SKIP generic {entry['claim_key']}: {exc}")
            counts["generic"]["skipped"] += 1

        try:
            r = gate_support(entry["title"], entry["rationale"], entry["quote"])
            _score(counts["support"], r.passed, wanted_ok("support"))
        except Exception as exc:
            print(f"  SKIP support {entry['claim_key']}: {exc}")
            counts["support"]["skipped"] += 1

        # Deterministic checks — always run.
        _score(counts["dtc_code"], not title_has_dtc_code(title), wanted_ok("dtc_code"))
        _score(counts["verbose"], not title_is_verbose(title), wanted_ok("verbose"))
        _score(counts["no_variant_anchor"], has_variant_anchor(title), wanted_ok("no_variant_anchor"))

        # cross_brand — detection test, not final verdict (see module docstring).
        own_makes = entry.get("own_makes")
        expect_flagged = entry.get("expect_flagged")
        if own_makes and expect_flagged is not None:
            contaminated = _mentions_other_brand(_claim_text(entry), set(own_makes))
            _score(counts["cross_brand"], contaminated == expect_flagged, True)
        else:
            counts["cross_brand"]["skipped"] += 1

    print(f"Gold set: {len(entries)} entries\n")
    for name in CHECKS:
        c = counts[name]
        n = c["tp"] + c["fp"] + c["tn"] + c["fn"]
        if n == 0:
            print(f"  {name:18s}: no applicable entries (skipped={c['skipped']})")
            continue
        precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
        recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
        print(
            f"  {name:18s}: TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}  "
            f"precision={precision:.2f} recall={recall:.2f}"
            + (f"  (skipped={c['skipped']})" if c["skipped"] else "")
        )

    print(
        "\nKnown gaps (no automated check exists yet): factually_impossible, "
        "non_automotive — see gold.yaml verdict_notes for the affected entries."
    )


if __name__ == "__main__":
    run()
