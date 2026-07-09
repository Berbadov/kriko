"""Ledger pipeline CLI.

    python -m knowledge.ledger.run all --max-usd 2.0
    python -m knowledge.ledger.run extract --dry-run
    python -m knowledge.ledger.run report

Every stage is resumable: extraction and verdicts are content-hash cached, so
rerunning after a BudgetExceeded abort (exit 2) continues where it stopped."""

import argparse
import sys
from pathlib import Path

from knowledge.ledger import cluster, db, export, extraction, ingest, resolve, verdict
from knowledge.ledger.costs import Budget, BudgetExceeded, log_stage

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_CLAIMS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "claims"
_EXPORT_DIR = Path(__file__).parent.parent / "ledger_export"


def _cmd_backfill(conn, args) -> None:
    d1, e1 = ingest.backfill_cache_dir(conn, _CACHE_DIR)
    d2, e2 = ingest.backfill_claims_dir(conn, _CLAIMS_DIR)
    blocked = ingest.flag_blocked_sources(conn)
    foreign = ingest.flag_foreign_language(conn)
    print(f"backfill: +{d1 + d2} documents, +{e1 + e2} evidence rows"
          f" ({blocked} blocked-source, {foreign} foreign-language flagged)")


def _cmd_extract(conn, args, budget) -> None:
    if args.dry_run:
        n, usd = extraction.pending_extraction_estimate(conn)
        print(f"extract --dry-run: {n} chunk call(s) planned, estimated ${usd:.4f}")
        return
    added = extraction.extract_pending(conn, budget)
    print(f"extract: +{added} evidence rows")


def _cmd_verdict(conn, args, budget) -> None:
    if args.dry_run:
        n, usd = verdict.pending_verdict_estimate(conn)
        print(f"verdict --dry-run: {n} cluster call(s) planned, estimated ${usd:.4f}")
        return
    saved = verdict.run_verdicts(conn, budget)
    print(f"verdict: {saved} verdict(s) stored")


def _cmd_export(conn, args) -> None:
    paths = export.export_all(conn, Path(args.export_dir))
    print(f"export: {len(paths)} file(s) -> {args.export_dir}")


def _cmd_report(conn) -> None:
    print(f"{'stage':<10} {'model':<26} {'calls':>6} {'tok_in':>9} {'tok_out':>9} {'usd':>9}")
    total = 0.0
    for r in conn.execute(
        "SELECT stage, model, SUM(calls), SUM(tokens_in), SUM(tokens_out), SUM(usd)"
        " FROM runs GROUP BY stage, model ORDER BY stage"):
        print(f"{r[0]:<10} {r[1]:<26} {r[2]:>6} {r[3]:>9} {r[4]:>9} {r[5]:>9.4f}")
        total += r[5]
    print(f"{'TOTAL':<10} {'':<26} {'':>6} {'':>9} {'':>9} {total:>9.4f}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="knowledge.ledger.run")
    p.add_argument("command", choices=[
        "backfill", "extract", "resolve", "cluster", "verdict", "export",
        "report", "all"])
    p.add_argument("--db", default=str(db.LEDGER_PATH))
    p.add_argument("--max-usd", type=float, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--export-dir", default=str(_EXPORT_DIR))
    args = p.parse_args(argv)

    conn = db.connect(args.db)
    budget = Budget(max_usd=args.max_usd)
    steps = {
        "backfill": lambda: _cmd_backfill(conn, args),
        "extract": lambda: _cmd_extract(conn, args, budget),
        "resolve": lambda: print(f"resolve: {resolve.resolve_all(conn)}"),
        "cluster": lambda: print(f"cluster: {cluster.rebuild_clusters(conn)} cluster(s)"),
        "verdict": lambda: _cmd_verdict(conn, args, budget),
        "export": lambda: _cmd_export(conn, args),
        "report": lambda: _cmd_report(conn),
    }
    order = (["backfill", "extract", "resolve", "cluster", "verdict", "export"]
             if args.command == "all" else [args.command])
    try:
        for name in order:
            steps[name]()
    except BudgetExceeded as exc:
        print(f"BUDGET ABORT: {exc}\n{budget.report()}")
        return 2
    finally:
        if budget.total_usd:
            for model, (calls, tin, tout, usd) in budget._by_model.items():
                log_stage(conn, args.command, model, calls, tin, tout, usd)
            print(budget.report())
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
