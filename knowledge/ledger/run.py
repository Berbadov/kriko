"""Ledger pipeline CLI.

    python -m knowledge.ledger.run acquire --part dw5 --part-type transmission
    python -m knowledge.ledger.run remediate --max-usd 2.0
    python -m knowledge.ledger.run all --max-usd 2.0
    python -m knowledge.ledger.run extract --dry-run
    python -m knowledge.ledger.run report

Every stage is resumable: extraction and verdicts are content-hash cached, so
rerunning after a BudgetExceeded abort (exit 2) continues where it stopped."""

import argparse
import sys
from pathlib import Path

from knowledge.ledger import (
    acquire, cluster, db, export, extraction, ingest, resolve, verdict,
)
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
        "acquire", "feeds", "backfill", "extract", "resolve", "cluster",
        "verdict", "export", "report", "remediate", "all"])
    p.add_argument("--db", default=str(db.LEDGER_PATH))
    p.add_argument("--max-usd", type=float, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--export-dir", default=str(_EXPORT_DIR))
    p.add_argument("--data-dir", default=str(Path(__file__).parent.parent.parent / "backend" / "data"),
                   help="catalog root with variants/, fitment/, parts/ (remediate)")
    # acquire-stage flags (no LLM — discovery/fetch only)
    p.add_argument("--part", help="part id to acquire sources for (e.g. dw5)")
    p.add_argument("--part-type", help="part type (engine|transmission|…)")
    p.add_argument("--fuel", default="", choices=["", "diesel", "petrol"])
    p.add_argument("--max-sources", type=int, default=15)
    p.add_argument("--max-per-query", type=int, default=5)
    p.add_argument("--no-youtube", action="store_true")
    # feeds-stage flags (structured sources, no LLM)
    p.add_argument("--feed", default="nhtsa", choices=["nhtsa", "safety_gate", "recalls_tr"])
    p.add_argument("--make", default="", help="feeds: limit to one make")
    p.add_argument("--model", default="", help="feeds: limit to one catalog model key")
    args = p.parse_args(argv)

    # $0 steady-state default (2026-08-03): remediate is import-only unless an
    # explicit LLM budget is given — coverage gaps get acquired + deterministic
    # import verdicts; paid research is an explicit opt-in for new parts.
    if args.command == "remediate" and args.max_usd is None:
        args.max_usd = 0.0

    conn = db.connect(args.db)
    budget = Budget(max_usd=args.max_usd)

    def _cmd_acquire() -> None:
        if not args.part:
            raise SystemExit("acquire requires --part (and usually --part-type)")
        part_type = args.part_type
        if not part_type:
            import yaml as _yaml
            from pathlib import Path as _Path
            for f in (_Path(__file__).parent.parent.parent
                      / "backend" / "data" / "parts").rglob(f"{args.part}.yaml"):
                part_type = (_yaml.safe_load(f.read_text()) or {}).get("part_type")
                break
        if not part_type:
            raise SystemExit(f"--part-type not given and no part YAML found for {args.part!r}")
        s = acquire.acquire_part(
            conn, args.part, part_type, fuel=args.fuel,
            max_sources=args.max_sources, max_per_query=args.max_per_query,
            youtube=not args.no_youtube)
        print(f"acquire[{args.part}]: {s['ingested']} ingested of "
              f"{s['discovered']} discovered "
              f"({s['skipped_duplicate']} dup, {s['skipped_fetch']} unfetchable, "
              f"{s['skipped_german']} german, {s['skipped_foreign']} foreign)")

    def _cmd_feeds() -> None:
        from knowledge.ledger.feeds import nhtsa, safety_gate, recalls_tr
        only = None
        if args.make or args.model:
            if not (args.make and args.model):
                raise SystemExit("feeds: --make and --model must be given together")
            only = (args.make, args.model)
        feed_map = {
            "nhtsa": (nhtsa, "nhtsa"),
            "safety_gate": (safety_gate, "safety_gate"),
            "recalls_tr": (recalls_tr, "recalls_tr"),
        }
        if args.feed not in feed_map:
            raise SystemExit(f"unknown feed: {args.feed}")
        module, name = feed_map[args.feed]
        per_model = module.run(conn, only=only)
        for model_name, s in per_model.items():
            ingested_key = "ingested"
            campaign_key = "campaigns" if "campaigns" in s else "alerts" if "alerts" in s else "recalls"
            print(f"feeds[{name}] {model_name}: {s[ingested_key]} recall(s) ingested "
                  f"({s.get(campaign_key, 0)} campaigns, {s['duplicates']} dup, "
                  f"{s['errors']} errors)")

    def _cmd_remediate(conn, args, budget) -> None:
        from knowledge.ledger import remediate
        if args.dry_run:
            report = remediate.build_report(
                Path(args.data_dir) / "variants",
                Path(args.data_dir) / "fitment",
                Path(args.data_dir) / "parts")
            plan = remediate.remediation_plan(report)
            print(f"remediate --dry-run: {len(report.findings)} finding(s), "
                  f"{len(plan)} part(s) would be re-researched: "
                  f"{[p for p, _ in plan] or 'none'}")
            return
        stats = remediate.run(
            conn, Path(args.data_dir), Path(args.export_dir), budget,
            max_sources=args.max_sources)
        n = len(stats["parts"])
        print(f"remediate: {n} part(s) re-researched "
              f"(+{stats['ingested']} docs, +{stats['lost_ingested']} lost-source"
              f" pages, +{stats['extracted']} evidence, "
              f"+{stats['verdicts']} verdicts, {stats['exported']} export file(s), "
              f"${stats['usd']:.4f})" if n else
              f"remediate: no actionable findings ({stats['findings']} total — "
              f"remaining kinds are not part-driven); logged to {remediate.LOG_PATH}")

    steps = {
        "acquire": _cmd_acquire,
        "feeds": _cmd_feeds,
        "backfill": lambda: _cmd_backfill(conn, args),
        "extract": lambda: _cmd_extract(conn, args, budget),
        "resolve": lambda: print(f"resolve: {resolve.resolve_all(conn)}"),
        "cluster": lambda: print(f"cluster: {cluster.rebuild_clusters(conn)} cluster(s)"),
        "verdict": lambda: _cmd_verdict(conn, args, budget),
        "export": lambda: _cmd_export(conn, args),
        "report": lambda: _cmd_report(conn),
        "remediate": lambda: _cmd_remediate(conn, args, budget),
    }
    order = (["backfill", "feeds", "extract", "resolve", "cluster", "verdict", "export"]
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
