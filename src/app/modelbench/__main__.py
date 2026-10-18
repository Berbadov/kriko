"""`python -m app.modelbench` — the benchmark without the application.

The reader's problem with the old benchmark was not that its button was ugly;
it was that the only way to run it was to press the button, and the only output
was a table on a screen. A measurement nobody can re-run, diff or attach to a
decision is folklore. So this exists:

    # what can this machine measure right now?
    python -m app.modelbench list

    # what would this sweep do, and what would it cost?
    python -m app.modelbench plan --candidates local:qwen3.5:4b,harness:mistral-vibe@glm-5-3

    # measure, and write JSON + CSV + Markdown
    python -m app.modelbench run \
        --candidates local:qwen3.5:4b,harness:mistral-vibe@glm-5-3 \
        --reps 2 --out .bench

    # re-cut a report that was already paid for, spending nothing
    python -m app.modelbench report --from .bench/modelbench-20261018-1615.json

Exit codes are the interface a script uses: `0` when every run happened, `1`
when some run failed (a measurement — see below), `2` when the request itself
was wrong.

**A failed run is not a failed command.** A candidate that cannot start is a
finding, so its row is written and the process still succeeds in the sense that
matters: it produced a report. Only a request that could not be carried out at
all — an unreadable corpus, a spec that names no kind — exits non-zero without
a report.
"""

import argparse
import json
import sys
from datetime import datetime, timezone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modelbench",
        description="Measure models on the controlled corpus: tokens and fabrication.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="candidates this machine can measure")
    listing.add_argument("--kind", action="append", default=[],
                         help="restrict to local, harness or api (repeatable)")
    listing.add_argument("--app-state", default="",
                         help="path to app.sqlite (defaults to this installation's)")
    listing.add_argument("--json", action="store_true", help="machine-readable")

    plan_cmd = sub.add_parser("plan", help="what a sweep would run")
    _common(plan_cmd)

    run_cmd = sub.add_parser("run", help="run a sweep and write a report")
    _common(run_cmd)
    run_cmd.add_argument("--out", default=".bench", help="directory for the report")
    run_cmd.add_argument("--stem", default="", help="report file stem")
    run_cmd.add_argument("--keep-answers", action="store_true",
                         help="store each raw reply in the JSON (large)")
    run_cmd.add_argument("--record", action="store_true",
                         help="also write the runs into this installation's "
                              "benchmark history, so the app can show them")
    run_cmd.add_argument("--quiet", action="store_true", help="only the summary")

    read_cmd = sub.add_parser(
        "report", help="re-render a report from a saved JSON, spending nothing")
    read_cmd.add_argument("--from", dest="source", required=True,
                          help="the JSON a previous run wrote")
    read_cmd.add_argument("--out", default="", help="directory (default: beside the JSON)")
    read_cmd.add_argument("--stem", default="", help="file stem (default: the JSON's)")
    read_cmd.add_argument("--title", default="", help="override the report title")
    read_cmd.add_argument("--when", default="", help="override the measured-at line")

    args = parser.parse_args(argv)
    if args.command == "list":
        return _list(args)
    if args.command == "plan":
        return _plan(args)
    if args.command == "report":
        return _report(args)
    return _run(args)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidates", default="",
                        help="comma-separated specs, e.g. "
                             "local:qwen3.5:4b,harness:mistral-vibe@glm-5-3; "
                             "empty means everything this machine can reach")
    parser.add_argument("--cases", type=int, default=0,
                        help="use only the first N cases (0 = all)")
    parser.add_argument("--reps", type=int, default=1,
                        help="repetitions of each case (a model is stochastic)")
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="seconds one run may take")
    parser.add_argument("--max-tokens", type=int, default=1024,
                        help="reply ceiling, where the transport honours one")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--app-state", default="",
                        help="path to app.sqlite (defaults to this installation's)")
    parser.add_argument("--json", action="store_true",
                        help="print the plan/result as JSON")


def _app_state(args) -> str:
    if args.app_state:
        return args.app_state
    from app.web.settings import Settings

    return str(Settings().app_state_path)


def _list(args) -> int:
    from app.modelbench import candidates as candidates_mod

    kinds = args.kind or None
    found = candidates_mod.discover(_app_state(args), kinds=kinds)
    if args.json:
        print(json.dumps([one.as_dict() for one in found], indent=2))
        return 0
    if not found:
        print("this machine can measure nothing right now.")
        print("start a local model server, install a coding-agent CLI, or set a key.")
        return 0
    print(f"{len(found)} candidate(s) this machine can measure:\n")
    width = max(len(one.id) for one in found)
    for one in found:
        print(f"  {one.id:<{width}}  {one.label}")
    print("\nRun one with:  python -m app.modelbench run --candidates "
          + found[0].id)
    return 0


def _plan(args) -> int:
    from app.modelbench import sweep

    try:
        found = sweep.plan(args.candidates, app_state_path=_app_state(args),
                           limit=args.cases, reps=args.reps)
    except ValueError as exc:
        print(f"cannot plan this sweep: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(found.as_dict(), indent=2))
        return 0
    print(f"{found.runs} run(s): {len(found.candidates)} candidate(s) x "
          f"{len(found.cases)} case(s) x {max(1, found.reps)} repetition(s)\n")
    for one in found.candidates:
        print(f"  {one.id:<40} {one.label}")
    return 0


def _run(args) -> int:
    from app.modelbench import report, sweep

    app_state = _app_state(args)
    try:
        planned = sweep.plan(args.candidates, app_state_path=app_state,
                             limit=args.cases, reps=args.reps)
    except ValueError as exc:
        print(f"cannot run this sweep: {exc}", file=sys.stderr)
        return 2
    if not planned.candidates:
        print("no candidate to measure. Try `list` first.", file=sys.stderr)
        return 2
    if not planned.cases:
        print("the corpus is empty.", file=sys.stderr)
        return 2

    total = planned.runs
    if not args.quiet:
        print(f"{total} run(s): {len(planned.candidates)} candidate(s) x "
              f"{len(planned.cases)} case(s) x {max(1, planned.reps)} rep(s)\n",
              flush=True)

    def narrate(row, done: int, count: int) -> None:
        if args.quiet:
            return
        where = f"[{done}/{count}]"
        if row.failed:
            detail = f"FAILED  {row.error[:70]}"
        else:
            score = row.score
            detail = (
                f"found {len(score.get('found') or [])}/{score.get('wanted', 0)}"
                f"  invented {score.get('fabricated', 0)}"
                f"  {row.reply.tokens_total if row.reply.tokens_total is not None else '—'} tok"
                f" ({row.reply.usage})"
                f"  {(row.ms or 0) / 1000:.1f}s"
            )
        print(f"{where:>9} {row.candidate_id:<38} {row.case_id:<20} {detail}",
              flush=True)

    rows = sweep.run(planned, app_state_path=app_state, timeout=args.timeout,
                     max_tokens=args.max_tokens or None,
                     temperature=args.temperature, on_row=narrate,
                     with_text=args.keep_answers)
    tables = sweep.tables(rows)
    when = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    stem = args.stem or f"modelbench-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    paths = report.write(
        args.out, rows, stem=stem,
        title="Model benchmark: tokens and fabrication",
        when=when, machine=_machine(),
    )
    _print_headline(tables["candidates"], args.quiet)
    if args.record:
        from app.modelbench import record

        written = record.record(
            app_state, rows, {one.get("id"): one for one in planned.cases})
        print(f"\nrecorded {written} run(s) into {app_state}")
    for name, path in paths.items():
        print(f"  {name:<16} {path}")
    return 0


def _report(args) -> int:
    """Re-render from a saved JSON. No model is reached, nothing is spent."""
    from app.modelbench import report

    try:
        paths = report.rerender(args.source, directory=args.out, stem=args.stem,
                                title=args.title, when=args.when)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.source}: {exc}", file=sys.stderr)
        return 2
    for name, path in paths.items():
        print(f"  {name:<16} {path}")
    return 0


def _print_headline(aggregate: list[dict], quiet: bool) -> None:
    print()
    header = f"{'candidate':<38} {'runs':>5} {'recall':>8} {'invent':>8} {'tok/fact':>10} {'p50':>7}"
    print(header)
    print("-" * len(header))
    for one in aggregate:
        def _pct(value):
            return "—" if value is None else f"{value * 100:.0f}%"

        def _num(value):
            return "—" if value is None else f"{value:,.0f}"

        p50 = "—" if one["latency_p50_ms"] is None else f"{one['latency_p50_ms'] / 1000:.1f}s"
        print(f"{one['candidate']:<38} {one['runs']:>5} "
              f"{_pct(one['recall']):>8} {_pct(one['hallucination_rate']):>8} "
              f"{_num(one['tokens_per_fact']):>10} {p50:>7}")
    failed = sum(one["failed"] for one in aggregate)
    if failed:
        print(f"\n{failed} run(s) failed — a measurement, not an error; see the report.")


def _machine() -> str:
    import platform

    return f"{platform.node()} ({platform.system()} {platform.release()}, " \
           f"Python {platform.python_version()})"


if __name__ == "__main__":
    sys.exit(main())
