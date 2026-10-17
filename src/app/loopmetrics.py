"""Loop metrics — how well the research loop itself is running.

The benches score an agent against gold (`app/gold.py`): what a run *found*.
This scores the loop: whether submits learned anything, whether the searches
were the agent's own work or re-rolls of the pack's seeds, and which queries
are dead ends. The raw material is the submission log every door writes
(`state.submissions_for`), so the metrics describe whichever door the work
came through — the same neutrality the acceptance path holds.

Each metric answers one question the loop's design raised:

* `first_pass_rate` vs `last_pass_rate` — did the verdicts teach it? A loop
  whose last submit survives the gate at the same rate as its first is not
  iterating; it is re-rolling.
* `findings_per_query` — is the run searching effectively at all?
* `seed_re_rolls` / `novel_query_share` — the loop's own failure mode,
  named: follow-ups were to come from the gaps, never from the seeds.
* `dead_queries` — the registry the brief renders back to the next run, as
  "do not repeat these".

Everything is computed from what the submissions actually said, with `None`
for anything the rows cannot answer — an invented number here would make the
one honest score look like a guess.
"""

from collections.abc import Sequence

#: The refusal heads that mean "the evidence was not real", rather than "the
#: claim was not worth keeping". The loop can teach the second kind; the
#: first means the quote was never copied honestly.
GROUNDING_HEADS = (
    "quote does not appear in the document text",
    "document_text missing",
)


def _pass_rate(run: dict) -> float | None:
    kept = len((run.get("verdicts") or {}).get("accepted") or [])
    refused = len((run.get("verdicts") or {}).get("rejected") or [])
    total = kept + refused
    return round(kept / total, 3) if total else None


def _queries(run: dict) -> list[str]:
    return [
        str(query).strip()
        for query in run.get("queries") or []
        if str(query).strip()
    ]


def score(rows: Sequence, seeds: Sequence[str] = ()) -> dict:
    """The loop metrics for one subject's submissions, oldest first.

    `rows` are submission rows as `state.submissions_for` reads them
    (`verdicts` and `queries` already parsed). `seeds` are the pack's
    rendered templates at score time — the re-roll question can only be
    asked against the seeds the run actually had, and a pack that changed
    its templates since is compared against what it ships now, which is the
    comparison an author tuning templates wants.
    """
    runs = [row for row in rows if isinstance(row, dict)]
    seed_set = {str(seed).strip() for seed in seeds if str(seed).strip()}

    kept = refused = grounding_failed = 0
    distinct: list[str] = []
    live: set[str] = set()
    per_run: list[dict] = []
    revised = 0
    for index, run in enumerate(runs):
        verdicts = run.get("verdicts") or {}
        accepted = verdicts.get("accepted") or []
        rejected = verdicts.get("rejected") or []
        already = verdicts.get("already_known") or []
        kept += len(accepted)
        refused += len(rejected)
        for one in rejected:
            head = str(one.get("reason") or "").split("—")[0].split(";")[0].strip()
            if any(head.startswith(g) for g in GROUNDING_HEADS):
                grounding_failed += 1
        queries = _queries(run)
        for query in queries:
            if query not in distinct:
                distinct.append(query)
        if accepted:
            live.update(queries)
        if index and any(one.get("fix") for one in
                         (runs[index - 1].get("verdicts") or {}).get("rejected") or []):
            revised += 1
        per_run.append({
            "kept": len(accepted),
            "refused": len(rejected),
            "already_known": len(already),
            "queries": len(queries),
            "pass_rate": _pass_rate(run),
        })

    novel = [query for query in distinct if query not in seed_set]
    dead = [query for query in distinct if query not in live]

    def _share(part: Sequence, whole: Sequence) -> float | None:
        return round(len(part) / len(whole), 3) if whole else None

    return {
        "submissions": len(runs),
        "kept": kept,
        "refused": refused,
        "grounding_failed": grounding_failed,
        "already_known": sum(one["already_known"] for one in per_run),
        "revised_runs": revised,
        "first_pass_rate": _pass_rate(runs[0]) if runs else None,
        "last_pass_rate": _pass_rate(runs[-1]) if runs else None,
        "distinct_queries": len(distinct),
        "findings_per_query": (
            round(kept / len(distinct), 3) if distinct and kept else
            (0.0 if distinct else None)
        ),
        "seed_re_rolls": len(distinct) - len(novel),
        "novel_query_share": _share(novel, distinct),
        "dead_queries": dead,
    }
