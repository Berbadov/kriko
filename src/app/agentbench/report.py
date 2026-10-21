"""From trials to a report a reader can act on, and argue from.

Terminal-Bench's number is the resolve rate: the share of tasks an agent
finished, with the trajectories behind it. This keeps that and adds what the
reader of five runs of one listing actually met: **consistency**. An agent that
resolves a task one run in three has not solved it, and a mean over runs hides
that. So each agent gets, per task, whether it resolved it *every* time
(`pass^k`) as well as *any* time (`pass@k`), and how much the set of claims
moved between runs.

Nothing is ranked across suites or across profiles: a number is only
comparable with another measured on the same tasks under the same settings.
"""

import json
import statistics
import time
from itertools import combinations
from pathlib import Path

from app.agentbench.checks import FAIL, NA, PASS, SETTINGS_CHECKS
from app.tuning import failures


def _jaccard(one: list, other: list) -> float:
    left, right = set(one), set(other)
    return 1.0 if not left and not right else len(left & right) / len(left | right)


def _median(values: list) -> float | None:
    values = [one for one in values if isinstance(one, (int, float))]
    return statistics.median(values) if values else None


def _rate(passed: int, failed: int) -> float | None:
    return round(passed / (passed + failed), 3) if passed + failed else None


def summarize(bench: dict) -> dict:
    """Aggregate a run's trials per agent, per task, per check and per dimension."""
    agents: dict[str, dict] = {}
    for agent in bench["agents"]:
        mine = [one for one in bench["trials"] if one["agent"] == agent]
        by_task: dict[str, list[dict]] = {}
        for one in mine:
            by_task.setdefault(one["task"], []).append(one)

        check_totals: dict[str, dict] = {}
        for one in mine:
            for check in one["checks"]:
                if check["status"] == NA:
                    continue
                bucket = check_totals.setdefault(check["name"], {"pass": 0, "fail": 0})
                bucket["pass" if check["status"] == PASS else "fail"] += 1

        dimensions: dict[str, list[int]] = {}
        tasks_summary: dict[str, dict] = {}
        stability: list[float] = []
        for name, runs in by_task.items():
            resolved = [one["resolved"] for one in runs]
            failing = sorted({check["name"] for one in runs for check in one["checks"]
                              if check["status"] == FAIL})
            first = next((one for one in runs if not one["resolved"]), None)
            why: list[str] = []
            if first is not None:
                why = [f"{check['name']}: {check['detail']}" for check in first["checks"]
                       if check["status"] == FAIL]
                if not why and first["error"]:
                    why = [first["error"]]
            tasks_summary[name] = {
                "resolved": sum(resolved), "runs": len(runs),
                "every_run": all(resolved), "any_run": any(resolved),
                "failing": failing, "why": why,
            }
            dimension = runs[0]["dimension"]
            dimensions.setdefault(dimension, []).extend(1 if one else 0 for one in resolved)
            if len(runs) > 1:
                stability.extend(_jaccard(a["claims"], b["claims"])
                                 for a, b in combinations(runs, 2))

        settings_pass = sum(check_totals.get(name, {}).get("pass", 0) for name in SETTINGS_CHECKS)
        settings_fail = sum(check_totals.get(name, {}).get("fail", 0) for name in SETTINGS_CHECKS)
        tokens = [one["measure"]["tokens"] for one in mine]
        agents[agent] = {
            "trials": len(mine), "tasks": len(by_task),
            "resolved_rate": round(sum(one["resolved"] for one in mine) / len(mine), 3) if mine else None,
            "every_run": sum(one["every_run"] for one in tasks_summary.values()),
            "any_run": sum(one["any_run"] for one in tasks_summary.values()),
            "grounded_rate": _rate(check_totals.get("grounded", {}).get("pass", 0),
                                   check_totals.get("grounded", {}).get("fail", 0)),
            "settings_rate": _rate(settings_pass, settings_fail),
            "stability": round(statistics.mean(stability), 3) if stability else None,
            "median_seconds": (lambda m: round(m / 1000, 1) if m is not None else None)(
                _median([one["measure"]["ms"] for one in mine])),
            "median_tokens": _median(tokens),
            "tokens_unmeasured": sum(1 for one in tokens if one is None),
            "refused": sum(one["measure"]["refused"] for one in mine),
            "errors": sum(1 for one in mine if one["error"]),
            # Why the unresolved trials failed, counted by class: the commonest
            # class is the next mechanism to build, not the next prompt to tweak.
            "failure_classes": failures.tally(mine),
            "commonest_failure": failures.commonest(failures.tally(mine)),
            "checks": check_totals,
            "dimensions": {name: round(sum(values) / len(values), 3)
                           for name, values in dimensions.items()},
            "task_results": tasks_summary,
        }
    return {"suite": bench["suite"], "profile": bench["profile"], "reps": bench["reps"],
            "tasks": bench["tasks"], "skipped": bench["skipped"], "agents": agents}


def _pct(value) -> str:
    return "-" if value is None else f"{round(value * 100)}%"


def _num(value, suffix: str = "") -> str:
    if value is None:
        return "-"
    return f"{value:g}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def render(summary: dict) -> str:
    """The report as Markdown: readable in a terminal, pasteable into a PR."""
    reps, agents = summary["reps"], summary["agents"]
    profile = summary["profile"]
    whose = "the reader's own settings" if profile == "reader" else "a clean state"
    lines = [
        f"# Agent benchmark: {summary['suite']['id']} {summary['suite']['version']}",
        "",
        f"{len(summary['tasks'])} task(s) x {reps} run(s) each, on a fixed web. "
        f"Settings profile: **{profile}** ({whose}). "
        "Only compare numbers measured on the same suite and profile.",
        "",
    ]
    if not agents:
        lines.append("No agent ran.")
    else:
        lines += ["## Agents", "",
                  f"| Agent | Resolved | Every run (pass^{reps}) | Any run (pass@{reps}) | Grounded "
                  "| Settings obeyed | Stable | Median s | Median tokens |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for name, one in agents.items():
            lines.append(
                f"| {name} | {_pct(one['resolved_rate'])} | {one['every_run']}/{one['tasks']} "
                f"| {one['any_run']}/{one['tasks']} | {_pct(one['grounded_rate'])} "
                f"| {_pct(one['settings_rate'])} | {_pct(one['stability'])} "
                f"| {_num(one['median_seconds'])} | {_num(one['median_tokens'])} |")
        lines += ["", "*Resolved* is the share of runs with no failed check. *Every run* counts tasks "
                  "resolved on all runs: the agent gave the right answer every time. *Stable* is how "
                  "much the set of delivered claims agrees between runs of one task.", ""]

        lines += ["## By task", "", "| Task | " + " | ".join(agents) + " |",
                  "|---|" + "---|" * len(agents)]
        for task in summary["tasks"]:
            cells = []
            for one in agents.values():
                got = one["task_results"].get(task)
                if got is None:
                    cells.append("-")
                    continue
                mark = "pass" if got["every_run"] else "FAIL" if not got["any_run"] else "flaky"
                cells.append(f"{mark} {got['resolved']}/{got['runs']}"
                             + (f" ({', '.join(got['failing'])})" if got["failing"] else ""))
            lines.append(f"| {task} | " + " | ".join(cells) + " |")

        names = sorted({d for one in agents.values() for d in one["dimensions"]})
        lines += ["", "## By skill", "", "| Skill | " + " | ".join(agents) + " |",
                  "|---|" + "---|" * len(agents)]
        for dimension in names:
            lines.append(f"| {dimension} | " + " | ".join(
                _pct(one["dimensions"].get(dimension)) for one in agents.values()) + " |")

        checks = sorted({c for one in agents.values() for c in one["checks"]})
        lines += ["", "## By check", "", "| Check | " + " | ".join(agents) + " |",
                  "|---|" + "---|" * len(agents)]
        for check in checks:
            cells = []
            for one in agents.values():
                got = one["checks"].get(check)
                cells.append("-" if not got else f"{got['pass']}/{got['pass'] + got['fail']}")
            lines.append(f"| {check} | " + " | ".join(cells) + " |")

        counted = sorted({c for one in agents.values() for c in one.get("failure_classes", {})},
                         key=list(failures.CLASSES).index)
        if counted:
            lines += ["", "## Why trials failed, by class", "",
                      "| Class | " + " | ".join(agents) + " |", "|---|" + "---|" * len(agents)]
            for name in counted:
                lines.append(f"| {name}: {failures.CLASSES[name]} | " + " | ".join(
                    str(one.get("failure_classes", {}).get(name, 0)) for one in agents.values()) + " |")
            lines += ["", "A trial with two classes counts in both. The commonest class is the "
                      "next mechanism to build: "
                      + "; ".join(f"{name}: {one['commonest_failure']}" for name, one in agents.items()
                                  if one.get("commonest_failure")) + ".", ""]

        why = [(name, task, result["why"]) for name, one in agents.items()
               for task, result in one["task_results"].items() if result["why"]]
        if why:
            lines += ["", "## Why runs failed", ""]
            for name, task, reasons in why:
                lines.append(f"* **{name}** on `{task}`: " + "; ".join(reasons[:3]))

    if summary["skipped"]:
        lines += ["", "## Not scored", ""]
        lines += [f"* {name}: {reason}" for name, reason in summary["skipped"].items()]
    return "\n".join(lines) + "\n"


def save(bench: dict, summary: dict, root: Path) -> Path:
    """Write the report and every trajectory under `root`, and return the directory."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = Path(root) / f"{stamp}-{bench['suite']['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.md").write_text(render(summary), encoding="utf-8")
    (folder / "report.json").write_text(
        json.dumps({"summary": summary, "trials": bench["trials"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return folder
