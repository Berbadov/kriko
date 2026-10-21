"""Before and after: paired differences with intervals, on the same cases.

*"A change to the engine (the brief, the mode rules, ranking) is judged by
running the same set before and after, with paired differences and intervals as
the bench already computes."* Two ledgers, one per run of the same set, are
paired by case and repetition. For each pair the difference is taken, and the
interval is the benchmark's own: a bootstrap over whole cases
(`metrics.cluster_interval`), because the repetitions of one case are not
independent evidence.

What is refused or flagged instead of smoothed over:

* **Different case sets** are not paired. Only the cases both ledgers hold are
  compared, and the comparison says how many were left out.
* **A different grader or grading protocol** confounds the difference with the
  grader; the comparison says so at the top, where it cannot be missed.
* **A different answerer** is a different question (one agent against another),
  and is labelled so; it is not a verdict on an engine change.
* A pass-rate difference is accompanied by the exact sign test over the pairs
  that changed verdict. With few cases the interval is wide and the report
  says it does not distinguish the runs, rather than naming a winner.

Nothing here calls an agent.
"""

import math
import statistics

from app.searchbench.metrics import cluster_interval
from app.tuning import failures


def _key(row: dict) -> tuple[str, int]:
    return row["case"], row["rep"]


def sign_test_p(improved: int, regressed: int) -> float | None:
    """Two-sided exact sign test over the pairs whose verdict changed."""
    changed = improved + regressed
    if not changed:
        return None
    tail = sum(math.comb(changed, k) for k in range(min(improved, regressed) + 1)) / 2 ** changed
    return min(1.0, 2 * tail)


def _delta(pairs: list[tuple[dict, dict]], pick) -> dict:
    values = []
    for first, second in pairs:
        a, b = pick(first), pick(second)
        if a is not None and b is not None:
            values.append({"case": first["case"], "delta": b - a})
    if not values:
        return {"pairs": 0, "mean": None, "ci95": None}
    return {"pairs": len(values), "mean": statistics.mean(one["delta"] for one in values),
            "ci95": cluster_interval(values, "delta")}


def compare(before: dict, after: dict) -> dict:
    """The paired comparison of two tuning ledgers, as plain data."""
    notes: list[str] = []
    same_set = before["case_set"]["sha256"] == after["case_set"]["sha256"]
    if not same_set:
        notes.append("the two runs did not ask the same questions: only the cases both hold are paired")
    if before["protocol"]["hash"] != after["protocol"]["hash"]:
        notes.append("the grading protocol differs between the runs: the difference is confounded "
                     "with the grader")
    if before["graded_by"].get("id") != after["graded_by"].get("id") or (
            before["graded_by"].get("model") != after["graded_by"].get("model")):
        notes.append("a different grader graded each run: the difference is confounded with the grader")
    first_agent = (before.get("answered_by") or {}).get("agent") or {}
    second_agent = (after.get("answered_by") or {}).get("agent") or {}
    same_answerer = (first_agent.get("id"), first_agent.get("model")) == (
        second_agent.get("id"), second_agent.get("model"))
    same_search = (before.get("answered_by") or {}).get("search_provider") == (
        after.get("answered_by") or {}).get("search_provider")
    if not same_answerer:
        notes.append("a different agent answered each run: this compares the agents, "
                     "not a change to the engine")
    if not same_search:
        notes.append("a different search provider was used in each run")
    if before["engine"].get("git_sha") and before["engine"].get("git_sha") == after["engine"].get("git_sha") and not (
            before["engine"].get("dirty") or after["engine"].get("dirty")):
        notes.append("both runs name the same engine commit: nothing changed between them, so "
                     "differences are noise")

    first = {_key(row): row for row in before["rows"]}
    second = {_key(row): row for row in after["rows"]}
    both = sorted(set(first) & set(second))
    graded = [(first[k], second[k]) for k in both
              if first[k]["accepted"] is not None and second[k]["accepted"] is not None]

    passes = [{"case": a["case"], "delta": int(b["accepted"]) - int(a["accepted"])} for a, b in graded]
    improved = [a["case"] for a, b in graded if not a["accepted"] and b["accepted"]]
    regressed = [a["case"] for a, b in graded if a["accepted"] and not b["accepted"]]
    still_failing = [a["case"] for a, b in graded if not a["accepted"] and not b["accepted"]]
    still_passing = [a["case"] for a, b in graded if a["accepted"] and b["accepted"]]

    def share(row: dict):
        total = row["grading"].get("claims_total") or 0
        return row["grading"].get("claims_supported", 0) / total if total else None

    pass_delta = statistics.mean(one["delta"] for one in passes) if passes else None
    interval = cluster_interval(passes, "delta") if passes else None
    result = {
        "before": {"label": before.get("label", ""), "summary": before["summary"],
                   "engine": before["engine"], "answered_by": before.get("answered_by"),
                   "graded_by": before["graded_by"]},
        "after": {"label": after.get("label", ""), "summary": after["summary"],
                  "engine": after["engine"], "answered_by": after.get("answered_by"),
                  "graded_by": after["graded_by"]},
        "notes": notes, "same_case_set": same_set,
        "paired": len(graded), "cases_compared": len({a["case"] for a, _ in graded}),
        "left_out": len(set(first) ^ set(second)) + (len(both) - len(graded)),
        "pass_rate": {"before": (sum(a["accepted"] for a, _ in graded) / len(graded)) if graded else None,
                      "after": (sum(b["accepted"] for _, b in graded) / len(graded)) if graded else None,
                      "delta": pass_delta, "ci95": interval},
        "improved": improved, "regressed": regressed,
        "still_failing": still_failing, "still_passing": still_passing,
        "sign_test_p": sign_test_p(len(improved), len(regressed)),
        "fact_credit": _delta(graded, lambda r: r["grading"].get("fact_credit")),
        "claims_supported": _delta(graded, share),
        "seconds": _delta(graded, lambda r: r.get("seconds")),
        "usd": _delta(graded, lambda r: r.get("usd")),
        "tokens": _delta(graded, lambda r: r.get("tokens")),
        "failure_classes": {"before": failures.tally([a for a, _ in graded]),
                            "after": failures.tally([b for _, b in graded])},
        "rows": [{"case": a["case"], "rep": a["rep"], "question": a["question"],
                  "before": a["status"], "after": b["status"],
                  "change": ("improved" if not a["accepted"] and b["accepted"]
                             else "regressed" if a["accepted"] and not b["accepted"] else "same"),
                  "fact_before": a["grading"].get("fact_credit"), "fact_after": b["grading"].get("fact_credit"),
                  "failures_before": a["failures"], "failures_after": b["failures"]}
                 for a, b in graded],
    }
    result["verdict"] = verdict(result)
    return result


def verdict(result: dict) -> str:
    """One honest sentence about what the pass-rate difference does and does not show."""
    delta, interval = result["pass_rate"]["delta"], result["pass_rate"]["ci95"]
    pairs = result["paired"]
    if delta is None:
        return "no case was graded in both runs, so there is nothing to compare."
    points = f"{delta * 100:+.1f} points"
    if interval is None:
        return (f"pass rate {points} over {pairs} pair(s), from one case only: no interval can be "
                "drawn and this is not evidence.")
    low, high = interval
    span = f"95% interval {low * 100:+.1f} to {high * 100:+.1f}"
    if low <= 0 <= high:
        return (f"pass rate {points} ({span}) over {result['cases_compared']} case(s): the interval "
                "includes zero, so the two runs are not distinguishable on this set.")
    direction = "rose" if delta > 0 else "fell"
    return (f"pass rate {direction} {abs(delta) * 100:.1f} points ({span}) over "
            f"{result['cases_compared']} case(s); the interval excludes zero. This is a "
            "model-graded measurement on this case set, not a population estimate.")
