"""Loop metrics: the loop is scored, not just the agent.

The benches score a run against gold — what was *found*. These metrics
score the loop itself, off the submission log every door writes:

* `first_pass_rate` against `last_pass_rate` — did the verdicts teach it?
* `findings_per_query` — is the searching effective at all?
* `seed_re_rolls` and `novel_query_share` — the loop's named failure mode:
  follow-ups were to come from the gaps, never from the seeds.
* `dead_queries` — the registry the brief renders back to the next run.

Every metric is computed from what the submissions actually said; anything
the rows cannot answer is `None`, because an invented number here would
make the one honest score look like a guess.
"""

from app.loopmetrics import score


def _run(accepted=(), rejected=(), queries=()):
    return {
        "verdicts": {
            "accepted": list(accepted),
            "rejected": list(rejected),
            "already_known": [],
        },
        "queries": list(queries),
    }


def test_no_history_answers_nothing_rather_than_zero():
    out = score([], seeds=("a query",))
    assert out["submissions"] == 0
    assert out["first_pass_rate"] is None
    assert out["findings_per_query"] is None
    assert out["novel_query_share"] is None
    assert out["dead_queries"] == []


def test_a_loop_that_learned_its_first_lesson():
    repairable = {"title": "t", "reason": "rationale is 0 chars — write two",
                  "fix": "rationale"}
    fabricated = {"title": "q", "reason":
                  "quote does not appear in the document text — copy it",
                  "fix": ""}
    first = _run(accepted=[{"title": "kept"}],
                 rejected=[repairable, fabricated],
                 queries=["seed one", "own query"])
    second = _run(accepted=[{"title": "mended"}, {"title": "found"}],
                 rejected=[],
                 queries=["own query", "gap query"])
    out = score([first, second], seeds=("seed one",))
    assert out["submissions"] == 2
    assert out["kept"] == 3 and out["refused"] == 2
    assert out["grounding_failed"] == 1
    assert out["revised_runs"] == 1, "the second submit followed a repair request"
    assert out["first_pass_rate"] == 0.333
    assert out["last_pass_rate"] == 1.0
    assert out["distinct_queries"] == 3
    assert out["findings_per_query"] == 1.0
    assert out["seed_re_rolls"] == 1, "one of the three was the pack's own seed"
    assert out["novel_query_share"] == 0.667
    assert out["dead_queries"] == [], "every query once led to something kept"


def test_dead_queries_are_only_the_ones_that_never_kept_anything():
    empty = _run(rejected=[{"title": "t", "reason": "no quote", "fix": ""}],
                 queries=["dead one", "live seed"])
    lucky = _run(accepted=[{"title": "kept"}], queries=["live seed"])
    out = score([empty, lucky], seeds=("live seed",))
    assert out["dead_queries"] == ["dead one"]
    assert out["seed_re_rolls"] == 1
    assert out["novel_query_share"] == 0.5


def test_grounding_failures_are_told_apart_from_value_refusals():
    fabricated = [{"title": "q", "reason":
                    "quote does not appear in the document text — copy it",
                    "fix": ""}]
    refused = [{"title": "t", "reason": "routine: true of any tool", "fix": ""}]
    out = score([_run(rejected=fabricated + refused)])
    assert out["grounding_failed"] == 1
    assert out["refused"] == 2
