"""Running a whole sweep: every candidate, every case, every repetition.

The order is deliberate and it is the same order the report prints: **cases
outside, candidates inside**. A reader watching the output sees one case
answered by every model in turn, which is the comparison they are making,
rather than one model's whole run before the next model starts. It also means a
sweep that is stopped early has, for the cases it reached, a complete row for
every candidate — so a half-finished run is still a smaller honest table instead
of one candidate with everything and three with nothing.

Cancellation is checked between runs and inside each one. A harness CLI in
flight is killed by the socket's own check callback; a local request is aborted
the same way. Nothing here swallows a `Cancelled`.
"""

from dataclasses import dataclass, field

from app.modelbench import aggregate as agg
from app.modelbench import candidates as candidates_mod
from app.modelbench import corpus
from app.modelbench.runner import Measurement, run_case


@dataclass
class Plan:
    """What a sweep will do, before it does it — so it can be printed first."""

    candidates: list = field(default_factory=list)
    cases: list = field(default_factory=list)
    reps: int = 1

    @property
    def runs(self) -> int:
        return len(self.candidates) * len(self.cases) * max(1, self.reps)

    def as_dict(self) -> dict:
        return {
            "candidates": [one.as_dict() for one in self.candidates],
            "cases": [{"id": one.get("id", ""), "dimension": one.get("dimension", "")}
                      for one in self.cases],
            "reps": max(1, self.reps),
            "runs": self.runs,
        }


def plan(specs=None, *, app_state_path=None, cases=None, limit: int = 0,
         suite: str = corpus.SUITE, reps: int = 1) -> Plan:
    """Resolve specs into candidates and load the corpus, or say what is wrong.

    A spec that names nothing available is *not* silently dropped: `parse_many`
    keeps it and the first run returns a row whose `error` says exactly why. A
    benchmark that quietly measured three of the four models someone asked for
    would be worse than one that failed.
    """
    found = (candidates_mod.parse_many(specs) if specs
             else candidates_mod.discover(app_state_path))
    chosen = corpus.load(suite)
    if limit:
        chosen = chosen[: max(1, int(limit))]
    problems = corpus.problems(chosen)
    if problems:
        # Loud, because every number this sweep produced would be wrong for a
        # reason that has nothing to do with any model.
        raise ValueError("the corpus is not usable: " + "; ".join(problems))
    return Plan(candidates=found, cases=chosen, reps=max(1, int(reps or 1)))


def run(plan_of: Plan, *, app_state_path=None, timeout: float = 300.0,
        max_tokens: int | None = 1024, temperature: float = 0.0,
        check_cancelled=None, on_row=None, with_text: bool = False) -> list[Measurement]:
    """Every run in the plan, in order, each one caught.

    `on_row(row, done, total)` is called after each measurement and after each
    failure, so a caller can narrate — a terminal, a job's progress line — while
    the sweep is still going. It is called *outside* the try that swallows
    failures: a bug in a progress callback is the caller's bug and must not be
    recorded as a model failure.
    """
    rows: list[Measurement] = []
    total = plan_of.runs
    done = 0
    for case in plan_of.cases:
        for candidate in plan_of.candidates:
            for rep in range(1, max(1, plan_of.reps) + 1):
                if check_cancelled is not None:
                    check_cancelled()
                row = run_case(
                    candidate, case, rep=rep, app_state_path=app_state_path,
                    timeout=timeout, max_tokens=max_tokens, temperature=temperature,
                    check_cancelled=check_cancelled, with_text=with_text,
                )
                rows.append(row)
                done += 1
                if on_row is not None:
                    on_row(row, done, total)
    return rows


def tables(rows: list[Measurement]) -> dict:
    """Every derived table, computed once from the same rows.

    One place, so the JSON, the CSV and the Markdown cannot disagree — which is
    exactly what happened when three modules each recomputed a rate.
    """
    return {
        "candidates": agg.by_candidate(rows),
        "dimensions": agg.by_dimension(rows),
        "cases": agg.by_case(rows),
        "summary": agg.summary(rows),
    }


__all__ = ["Plan", "plan", "run", "tables"]
