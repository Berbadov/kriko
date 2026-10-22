"""`python -m app.searchbench tune ...` (also `python -m app.tuning ...`).

    tune list                    who would answer and grade, and the saved chats; spends nothing
    tune propose --thread ID     cases proposed from the chats you name; local, spends nothing
    tune run                     the plan and its cost; add --yes to run it
    tune compare BEFORE AFTER    paired before/after report from two ledgers; spends nothing
    tune report FOLDER           rebuild a run's report; spends nothing

**Nothing is spent unasked.** `tune run` prints who would answer, who would
grade, the number of calls and the upper-bound cost, and stops with exit code 2
until `--yes` is given. The answerer is the reader's preferred agent and search
provider from Settings; the grader is another agent, never the same one.
"""

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import prefs
from app.tuning import agents as agent_mod
from app.tuning import cases as cases_mod
from app.tuning import compare as compare_mod
from app.tuning import cost, report, run
from app.tuning.sandbox import sandbox


@dataclass
class Dependencies:
    """The edges of a run, replaceable so a test (or a dry rehearsal) spends nothing."""

    roster: Callable[..., Any] = agent_mod.roster
    answerer: Callable[..., Any] | None = None
    open_grader: Callable[..., Any] = agent_mod.open_agent
    fetch: Callable[..., Any] | None = None

    def make_answerer(self, state_path, preference, args):
        if self.answerer is not None:
            return self.answerer(state_path, preference, args)
        from app.tuning.answer import ChatAnswerer

        return ChatAnswerer(state_path, preference, timeout=args.timeout,
                            override_agent=bool(args.answerer), override_search=bool(args.search))

    def make_fetch(self):
        if self.fetch is not None:
            return self.fetch
        from app import chatweb

        return chatweb.reader(timeout=8.0)


def _state_path(args) -> Path:
    if args.state:
        return Path(args.state)
    from app.web.settings import Settings

    return Settings().app_state_path


def _add_common(parser) -> None:
    parser.add_argument("--state", default="", help="the app.sqlite to read Settings from "
                        "(default: this machine's)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tune", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="who would answer and grade; saved chats; spends nothing")
    _add_common(listing)

    propose = commands.add_parser("propose", help="propose cases from the saved chats you name; local only")
    _add_common(propose)
    propose.add_argument("--thread", action="append", default=[], metavar="ID",
                         help="a conversation to take questions from (repeatable); none named lists them")
    propose.add_argument("--follow-ups", action="store_true", help="also take later questions, with their history")
    propose.add_argument("--limit", type=int, default=50)
    propose.add_argument("--out", default="", help="write the proposed cases to this JSON file for you to edit")

    runner = commands.add_parser("run", help="answer and grade a case set (prints the cost; --yes to run)")
    _add_common(runner)
    runner.add_argument("--cases", action="append", default=[], metavar="FILE",
                        help="a case file (repeatable); with none, the benchmark corpus is used")
    runner.add_argument("--bench", action="store_true", help="include the benchmark corpus beside --cases")
    runner.add_argument("--limit", type=int, default=0, help="only the first N cases (a rehearsal, not a verdict)")
    runner.add_argument("--reps", type=int, default=1)
    runner.add_argument("--label", default="", help="a name for this run, e.g. before or after")
    runner.add_argument("--answerer", default="", metavar="AGENT",
                        help="answer with this agent instead of the one picked in Settings")
    runner.add_argument("--search", default="", metavar="PROVIDER",
                        help="search with this provider instead of the one picked in Settings")
    runner.add_argument("--grader", default="", metavar="AGENT",
                        help="grade with this agent (never the answerer); default: the first other one")
    runner.add_argument("--timeout", type=float, default=300.0, help="seconds one case may take")
    runner.add_argument("--seed", type=int, default=42)
    runner.add_argument("--out", default=".local-evaluation/tuning")
    runner.add_argument("--yes", action="store_true",
                        help="spend the agents named above; without it the plan is printed and nothing runs")

    comparison = commands.add_parser("compare", help="paired before/after comparison of two ledgers")
    comparison.add_argument("before")
    comparison.add_argument("after")
    comparison.add_argument("--out", default="", help="where to write compare.html (default: beside AFTER)")

    rebuild = commands.add_parser("report", help="rebuild a run's report from its ledger")
    rebuild.add_argument("folder")
    return parser


def _list(args, deps: Dependencies) -> int:
    path = _state_path(args)
    agents = deps.roster(path)
    print("agents available:", ", ".join(f"{one.id} ({one.kind})" for one in agents) or "none")
    try:
        preference = agent_mod.read_preference(path, agents)
        print(f"answers (from Settings): {preference.agent.label} ({preference.agent.id}"
              f"{', ' + preference.agent.model if preference.agent.model else ''}); "
              f"search: {preference.search_provider}")
        print(f"would be graded by: {agent_mod.choose_grader(preference.agent, agents).label}")
    except agent_mod.AgentUnavailable as problem:
        print(f"cannot run: {problem}")
    from app.web import state

    conn = state.connect(path)
    try:
        threads = cases_mod.saved_threads(conn)
    finally:
        conn.close()
    print(f"\n{len(threads)} saved conversation(s); `tune propose --thread ID` takes questions "
          "from the ones you name.")
    for one in threads[:15]:
        print(f"  {one['thread_id']}  {one['questions']:>3} question(s)  {one['title'][:60]}")
    return 0


def _propose(args, deps: Dependencies) -> int:
    from app.web import state

    conn = state.connect(_state_path(args))
    try:
        if not args.thread:
            print("name the conversations to take questions from; nothing is read until you do:")
            for one in cases_mod.saved_threads(conn)[:30]:
                print(f"  --thread {one['thread_id']}   {one['questions']} question(s)   {one['title'][:60]}")
            return 0
        proposed = cases_mod.propose_from_chats(conn, args.thread, follow_ups=args.follow_ups,
                                                limit=args.limit)
    finally:
        conn.close()
    if not proposed:
        print("no usable question in those conversations", file=sys.stderr)
        return 1
    if args.out:
        import json

        Path(args.out).write_text(json.dumps({"cases": proposed}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"{len(proposed)} case(s) written to {args.out}. Nothing was sent anywhere. Open it, delete any "
              "question you would not want asked, and run it with `tune run --cases FILE`.")
    else:
        for case in proposed:
            print(f"{case['id']}: {case['question']}")
    return 0


def _run(args, deps: Dependencies) -> int:
    path = _state_path(args)
    cases: list[dict] = []
    if args.bench or not args.cases:
        cases += cases_mod.bench_cases()
    for file in args.cases:
        cases += cases_mod.load_file(Path(file))
    if args.limit:
        cases = cases[:args.limit]
    try:
        cases_mod.validate(cases)
        agents = deps.roster(path)
        preference = agent_mod.read_preference(path, agents, agent=args.answerer, search=args.search)
        grader_ref = agent_mod.choose_grader(preference.agent, agents, args.grader)
    except (ValueError, agent_mod.AgentUnavailable) as problem:
        print(f"nothing was run: {problem}", file=sys.stderr)
        return 2
    shape = cost.plan(cases, preference.agent, grader_ref, preference.search_provider, reps=args.reps)
    print(cost.describe(shape))
    if preference.note:
        print(f"note: {preference.note}")
    if not args.yes:
        print("\nNothing was run. Spending your agents is your decision: add --yes to run this.",
              file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = Path(args.out) / f"tuning-{stamp}{'-' + args.label if args.label else ''}"
    answerer = deps.make_answerer(path, preference, args)
    overrides = {prefs.HARNESS: grader_ref.id}
    with sandbox(path, overrides=overrides) as grading_settings:
        from app.tuning.grade import Grader

        grader = Grader(deps.open_grader(grader_ref, grading_settings))
        total = len(cases) * max(1, args.reps)
        done = {"n": 0}

        def progress(row: dict) -> None:
            done["n"] += 1
            print(f"[{done['n']}/{total}] {row['case']}: {row['status']}"
                  f"{'  ' + ', '.join(row['failures']) if row['failures'] else ''}", flush=True)

        document = run.run_tuning(
            cases, answerer, grader, fetch=deps.make_fetch(), folder=folder, label=args.label,
            reps=args.reps, seed=args.seed, preference=preference.public(), on_row=progress)
    # The report is built from the ledger on disk, which is scrubbed, never from
    # what was held in memory.
    document = run.load(folder)
    index = report.build(document, folder / "report")
    summary = document["summary"]
    rate = "no graded attempt" if summary["pass_rate"] is None else f"{summary['accepted']}/{summary['graded']}"
    print(f"\naccepted {rate}; commonest failure: {summary['commonest_failure'] or 'none'}")
    print(f"ledger {folder / 'results.json'}\nreport {index}")
    print("To judge an engine change, run this on the old engine with --label before, again after the "
          f"change with --label after, then: tune compare {folder.parent}/<before> {folder.parent}/<after>")
    return 0


def _compare(args, deps: Dependencies) -> int:
    before, after = run.load(Path(args.before)), run.load(Path(args.after))
    result = compare_mod.compare(before, after)
    out = Path(args.out) if args.out else (Path(args.after) if Path(args.after).is_dir()
                                           else Path(args.after).parent) / "report"
    path = report.build_comparison(result, out)
    for note in result["notes"]:
        print(f"note: {note}")
    print(result["verdict"])
    print(path)
    return 0


def _report(args, deps: Dependencies) -> int:
    document = run.load(Path(args.folder))
    folder = Path(args.folder) if Path(args.folder).is_dir() else Path(args.folder).parent
    print(report.build(document, folder / "report"))
    return 0


def main(argv=None, deps: Dependencies | None = None) -> int:
    deps = deps or Dependencies()
    args = build_parser().parse_args(argv)
    handler = {"list": _list, "propose": _propose, "run": _run,
               "compare": _compare, "report": _report}[args.command]
    return handler(args, deps)
