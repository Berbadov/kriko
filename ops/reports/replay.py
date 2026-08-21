"""Replay a logged /analyze request through the CURRENT pipeline and diff the result.

docs/design_flaws.md "Observability gap", fix step 3: after a promote.py/gate/fitment
fix, feed a previously-logged request (e.g. one with sibling-code contamination or an
ambiguous match) back through the real serve path and see whether it's actually fixed
— without needing to reproduce the listing in a browser.

Calls backend.api.main.run_analysis() directly — the same function the /analyze route
calls — so this never drifts into testing a reimplementation of the pipeline.

    python -m ops.reports.replay <analysis-id>
    python -m ops.reports.replay --last 5      # replay the N most recent
"""

import argparse

from sqlalchemy.orm import Session

from backend.api.main import run_analysis
from backend.db.session import SessionLocal
from backend.observability import read_by_id, read_recent


def _risk_titles(resp: dict) -> set[str]:
    return {r["title"] for r in (resp or {}).get("risks", [])}


def compute_diff(logged_resp: dict, new_resp: dict) -> list[str]:
    """Pure diff between a logged response and a freshly-computed one.

    Returns human-readable change lines (empty list = no change). Kept separate
    from I/O so it's testable without a live DB/SessionLocal.
    """
    lines: list[str] = []

    logged_state, new_state = logged_resp.get("coverage_state"), new_resp.get("coverage_state")
    if logged_state != new_state:
        lines.append(f"coverage_state: {logged_state!r} -> {new_state!r}")

    logged_variants = set(logged_resp.get("matched_variant_ids") or [])
    new_variants = set(new_resp.get("matched_variant_ids") or [])
    if logged_variants != new_variants:
        lines.append(f"matched_variant_ids: {sorted(logged_variants)} -> {sorted(new_variants)}")

    logged_titles = _risk_titles(logged_resp)
    new_titles = _risk_titles(new_resp)
    added = new_titles - logged_titles
    removed = logged_titles - new_titles
    if added:
        lines.append(f"+ now shown: {sorted(added)}")
    if removed:
        lines.append(f"- no longer shown: {sorted(removed)}")

    return lines


def _diff_and_print(record: dict, db: Session) -> None:
    """db is injected (rather than opened here) so this same function can be
    exercised in tests against the in-memory fixture DB — see
    backend/tests/test_observability.py.
    """
    logged_resp = record.get("response") or {}
    meta        = record.get("ad_metadata") or {}
    analysis_id = record.get("id", "?")

    try:
        _ctx, _match, _served, new_resp = run_analysis(meta, db)
    except Exception as exc:
        print(f"[{analysis_id}] REPLAY ERROR: {exc}")
        return

    print(f"[{analysis_id}] {meta.get('make', '?')} {meta.get('model', '?')} {meta.get('year', '?')}")
    diff = compute_diff(logged_resp, new_resp.model_dump(mode="json"))
    if not diff:
        print("  no change")
    for line in diff:
        print(f"  {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis_id", nargs="?", default=None, help="Specific analysis id to replay")
    parser.add_argument("--last", type=int, default=None, help="Replay the N most recent analyses instead")
    args = parser.parse_args()

    if args.analysis_id:
        record = read_by_id(args.analysis_id)
        if record is None:
            print(f"No logged analysis with id={args.analysis_id!r}")
            return
        records = [record]
    else:
        records = read_recent(limit=args.last or 5)
        if not records:
            print("No analyses logged yet.")
            return

    db = SessionLocal()
    try:
        for record in records:
            _diff_and_print(record, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
