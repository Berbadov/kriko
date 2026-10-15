"""`kriko agent-bench`: run the suite from a terminal.

A benchmark whose output is an argument ("this agent resolves seven tasks in
eleven and gives a different answer on three") has to be runnable where the
sentence is pasted from, and watched while it runs.

**It never spends an agent unasked.** Naming a real agent without `--yes` prints
what would run and stops. The scripted agents (`--simulate`) are free and always
allowed: they are how the benchmark checks itself.
"""

import sys
from pathlib import Path

from app.agentbench import report, runner, simulated, suite


def add_arguments(p) -> None:
    p.add_argument("--agents", default="",
                   help="comma-separated: local, codex, antigravity-cli, mistral-vibe, "
                        "or sim:<name> for a scripted agent")
    p.add_argument("--simulate", action="store_true",
                   help="run every scripted agent (free); checks the checks")
    p.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    p.add_argument("--reps", type=int, default=3,
                   help="runs per agent per task (default 3; consistency needs more than one)")
    p.add_argument("--profile", choices=runner.PROFILES, default="reader",
                   help="reader: the settings you set in the app; clean: a fresh state "
                        "(comparable between machines)")
    p.add_argument("--timeout", type=float, default=runner.TRIAL_TIMEOUT_SECONDS,
                   help="seconds one run may take")
    p.add_argument("--yes", action="store_true",
                   help="allow real agents to run (this spends their subscription)")
    p.add_argument("--list", action="store_true", help="show the tasks and which agents can run")
    p.add_argument("--out", default="", help="where to write the report and trajectories")
    p.add_argument("--fail-under", type=float, default=0.0,
                   help="exit 1 when any agent's resolved rate is below this percentage")


def _state_dir(args) -> Path:
    from app.web.settings import Settings

    if getattr(args, "store", None):
        return Path(args.store).parent
    return Settings().app_state_path.parent


def run(args) -> int:
    loaded = suite.load([one for one in args.tasks.split(",") if one.strip()])
    problems = suite.validate(loaded)
    if problems:
        print("the suite is inconsistent, so nothing can be trusted:\n  " + "\n  ".join(problems),
              file=sys.stderr)
        return 1
    state_dir = _state_dir(args)

    if args.list:
        print(f"{loaded['id']} {loaded['version']}: {len(loaded['tasks'])} task(s)\n")
        for task in loaded["tasks"]:
            print(f"  {task['id']:<22} {task.get('dimension', ''):<18} {task.get('about', '')[:70]}")
        print("\nagents:")
        for name in ["local", "codex", "antigravity-cli", "mistral-vibe", *simulated.names()]:
            try:
                runner.classify(name)
                print(f"  {name:<22} can run")
            except runner.AgentUnavailable as why:
                print(f"  {name:<22} {why}")
        return 0

    agents = [one.strip() for one in args.agents.split(",") if one.strip()]
    if args.simulate:
        agents += [one for one in simulated.names() if one not in agents]
    if not agents:
        print("name the agents to run: --agents codex,antigravity-cli, or --simulate. "
              "--list shows which can run here.", file=sys.stderr)
        return 2
    real = [one for one in agents if not simulated.is_simulated(one)]
    trials = len(loaded["tasks"]) * len(agents) * max(1, args.reps)
    if real and not args.yes:
        print(f"This would run {', '.join(real)}: {trials} trial(s) in all "
              f"({len(loaded['tasks'])} task(s) x {max(1, args.reps)} run(s) per agent).\n"
              "Each trial is one real CLI call on your subscription. "
              "Add --yes to run them; --simulate runs the scripted agents for free.",
              file=sys.stderr)
        return 2

    def progress(trial: dict) -> None:
        mark = "pass" if trial["resolved"] else "FAIL"
        failed = [one["name"] for one in trial["checks"] if one["status"] == "fail"]
        print(f"  {mark}  {trial['agent']:<18} {trial['task']:<20} run {trial['rep']}"
              + (f"  ({', '.join(failed)})" if failed else "")
              + (f"  [{trial['error'][:80]}]" if trial["error"] else ""), flush=True)

    print(f"{loaded['id']} {loaded['version']}: {trials} trial(s), profile {args.profile}")
    bench = runner.run_bench(
        loaded["tasks"], agents, reps=args.reps, profile=args.profile,
        reader_state=state_dir / "app.sqlite", timeout=args.timeout, on_trial=progress)
    summary = report.summarize(bench)
    print()
    print(report.render(summary))
    folder = report.save(bench, summary, Path(args.out) if args.out else state_dir / "bench")
    print(f"report and trajectories: {folder}")
    if args.fail_under:
        low = [name for name, one in summary["agents"].items()
               if (one["resolved_rate"] or 0) * 100 < args.fail_under]
        if low:
            print(f"below {args.fail_under:g}%: {', '.join(low)}", file=sys.stderr)
            return 1
    return 0
