"""Rolling measurements up into the table the model choice is actually made from.

Two rules decide everything here.

**Pool, never average rates.** Recall across a sweep is `sum(found) /
sum(wanted)`, not the mean of each case's recall. The two differ whenever cases
have unequal numbers of facts, and the mean-of-rates answer lets a case with one
fact outvote a case with four. The same applies to hallucination: the
denominator is items produced, so a model that produces nothing does not score a
flawless 0%.

**A failure is in the denominator.** A candidate that failed four of ten cases
has a failure rate of 0.4 and a recall computed from the six it managed — with
the failure rate printed *next to* it. Dropping failures, or scoring them as
zero recall, are the two ways this table could mislead; both are refused.

And one figure carries the decision: **tokens per expected fact found**. It is
the only cost column that punishes both overspending and under-delivering, and
it is computed only from genuinely metered runs, so a guessed number can never
decide which model is efficient.
"""

from app.modelbench import metrics


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    import math

    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[min(index, len(ordered) - 1)]


def _empty() -> dict:
    return {
        "runs": 0, "graded": 0, "failed": 0,
        "wanted": 0, "found": 0, "produced": 0, "fabricated": 0,
        "unsupported_quotes": 0,
        "specs_wanted": 0, "specs_found": 0, "specs_produced": 0, "specs_wrong": 0,
        "abstentions_expected": 0, "abstentions_correct": 0,
        "passed": 0, "shaped": 0,
        "metered_runs": 0, "estimated_runs": 0, "unmetered_runs": 0,
        "tokens_total_sum": 0, "tokens_in_sum": 0, "tokens_out_sum": 0,
        "tokens_in_runs": 0, "tokens_out_runs": 0,
        "usd_sum": 0.0, "priced_runs": 0,
        "_latencies": [], "_totals": [], "_errors": [],
    }


def _absorb(seen: dict, row) -> None:
    seen["runs"] += 1
    if row.failed:
        seen["failed"] += 1
        seen["_errors"].append(row.error)
    if row.reply.metered:
        seen["metered_runs"] += 1
        if row.reply.tokens_total is not None:
            seen["tokens_total_sum"] += row.reply.tokens_total
            seen["_totals"].append(row.reply.tokens_total)
        if row.reply.tokens_in is not None:
            seen["tokens_in_sum"] += row.reply.tokens_in
            seen["tokens_in_runs"] += 1
        if row.reply.tokens_out is not None:
            seen["tokens_out_sum"] += row.reply.tokens_out
            seen["tokens_out_runs"] += 1
    elif row.reply.usage == "estimated":
        seen["estimated_runs"] += 1
    else:
        seen["unmetered_runs"] += 1
    if row.reply.usd is not None:
        seen["usd_sum"] += float(row.reply.usd)
        seen["priced_runs"] += 1
    if row.ms is not None:
        seen["_latencies"].append(float(row.ms))
    if not row.graded:
        return
    seen["graded"] += 1
    score = row.score
    seen["wanted"] += int(score.get("wanted") or 0)
    seen["found"] += len(score.get("found") or [])
    seen["produced"] += int(score.get("produced") or 0)
    seen["fabricated"] += int(score.get("fabricated") or 0)
    seen["unsupported_quotes"] += int(score.get("unsupported_quotes") or 0)
    seen["specs_wanted"] += int(score.get("specs_wanted") or 0)
    seen["specs_found"] += len(score.get("spec_found") or [])
    # A specification the model *returned* with the wrong name, value or URL.
    # Counted apart from `spec_found` and `spec_missed` because it is a
    # different failure: omitting a figure is a gap, and stating the wrong one
    # confidently is the fabrication this benchmark exists to catch. A model
    # that returns nothing scores no wrong specs and must not look careful.
    seen["specs_produced"] += int(score.get("specs_produced") or 0)
    seen["specs_wrong"] += len(score.get("spec_errors") or [])
    if score.get("abstention_correct") is not None:
        seen["abstentions_expected"] += 1
        seen["abstentions_correct"] += int(bool(score["abstention_correct"]))
    if score.get("pass"):
        seen["passed"] += 1
    if score.get("valid_shape"):
        seen["shaped"] += 1


def _finish(seen: dict) -> dict:
    latency = seen.pop("_latencies")
    totals = seen.pop("_totals")
    errors = seen.pop("_errors")
    out = dict(seen)
    out["recall"] = metrics.rate(seen["found"], seen["wanted"])
    out["recall_interval"] = metrics.interval(seen["found"], seen["wanted"])
    out["hallucination_rate"] = metrics.rate(seen["fabricated"], seen["produced"])
    out["hallucination_interval"] = metrics.interval(seen["fabricated"], seen["produced"])
    out["spec_recall"] = metrics.rate(seen["specs_found"], seen["specs_wanted"])
    # Of the specifications it *did* return, how many were wrong. The pair
    # matters: a model can have perfect spec recall by returning nothing, and
    # this is the column that refuses to reward that.
    out["spec_error_rate"] = metrics.rate(seen["specs_wrong"], seen["specs_produced"])
    out["spec_error_interval"] = metrics.interval(seen["specs_wrong"],
                                                  seen["specs_produced"])
    out["abstention_accuracy"] = metrics.rate(seen["abstentions_correct"],
                                              seen["abstentions_expected"])
    out["pass_rate"] = metrics.rate(seen["passed"], seen["graded"])
    # How often the answer even had the requested shape. Printed because it is
    # the difference between two failures that look identical in the rates: a
    # model that produces nothing parseable has no hallucination *rate* at all
    # (`None`, not 0%), and a reader who only saw that dash could mistake it for
    # a flawless model.
    out["valid_shape_rate"] = metrics.rate(seen["shaped"], seen["graded"])
    out["failure_rate"] = metrics.rate(seen["failed"], seen["runs"])
    # Means over metered runs only. An estimated or absent count is not a
    # smaller number, it is no number, and averaging it in as one would let a
    # candidate that meters nothing look cheapest.
    out["tokens_total_mean"] = (
        round(seen["tokens_total_sum"] / seen["metered_runs"], 1)
        if seen["metered_runs"] else None
    )
    out["tokens_total_median"] = (
        round(sorted(totals)[len(totals) // 2], 1) if totals else None
    )
    out["tokens_in_mean"] = (
        round(seen["tokens_in_sum"] / seen["tokens_in_runs"], 1)
        if seen["tokens_in_runs"] else None
    )
    out["tokens_out_mean"] = (
        round(seen["tokens_out_sum"] / seen["tokens_out_runs"], 1)
        if seen["tokens_out_runs"] else None
    )
    # Two cost figures, and the objective names both, so they are both here.
    #
    # `tokens_per_fact` is cost per **correct answer**: counted tokens over
    # expected facts found. It is the column a model choice turns on, because it
    # is the only one that punishes overspending *and* under-delivering — a
    # cheap model that found nothing does not win it.
    #
    # `tokens_per_accepted` is cost per **accepted claim**: counted tokens over
    # items the model put forward that the key could support. On this corpus the
    # two denominators coincide, because an item is either a matched expected
    # fact or an unsupported claim — there is no "grounded but unlisted" bucket
    # here. They come apart on the pack-derived suites, where a genuinely new
    # finding is accepted without being in the key, and `protocols.readout`
    # already computes this name. Kept distinct so the two reports cannot drift.
    out["tokens_per_fact"] = (
        round(seen["tokens_total_sum"] / seen["found"], 1)
        if seen["metered_runs"] and seen["found"] else None
    )
    out["accepted"] = seen["found"]
    out["tokens_per_accepted"] = out["tokens_per_fact"]
    out["tokens_per_claim"] = (
        round(seen["tokens_total_sum"] / seen["produced"], 1)
        if seen["metered_runs"] and seen["produced"] else None
    )
    out["usd_total"] = round(seen["usd_sum"], 6) if seen["priced_runs"] else None
    out["usd_per_fact"] = (
        round(seen["usd_sum"] / seen["found"], 6)
        if seen["priced_runs"] and seen["found"] else None
    )
    out["usd_per_accepted"] = out["usd_per_fact"]
    out["latency_p50_ms"] = _percentile(latency, 0.50)
    out["latency_p95_ms"] = _percentile(latency, 0.95)
    out["failures"] = _failure_summary(errors)
    return out


def _failure_summary(errors: list[str]) -> list[dict]:
    """Distinct failures with counts, most common first.

    A distribution rather than a count: "four of five failed, all of them
    unable to start" is a sentence a reader can act on — fix the CLI — and
    "four of five failed" is not.
    """
    counts: dict[str, int] = {}
    for one in errors:
        counts[one] = counts.get(one, 0) + 1
    return [
        {"error": error, "count": count}
        for error, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def by_candidate(rows: list) -> list[dict]:
    """One row per candidate, in the order the candidates were given."""
    order: list[str] = []
    groups: dict[str, dict] = {}
    labels: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for row in rows:
        if row.candidate_id not in groups:
            order.append(row.candidate_id)
            groups[row.candidate_id] = _empty()
            labels[row.candidate_id] = row.candidate_label
            kinds[row.candidate_id] = row.kind
        _absorb(groups[row.candidate_id], row)
    out = []
    for name in order:
        one = _finish(groups[name])
        one["candidate"] = name
        one["candidate_label"] = labels[name]
        one["kind"] = kinds[name]
        out.append(one)
    return out


def by_dimension(rows: list) -> list[dict]:
    """The same roll-up per (candidate, case dimension).

    The aggregate says *how much* a model fails; this says *where*, and for a
    model choice that is often the whole answer. A model that is perfect except
    on `distractor-load` is a different proposition from one that is mediocre
    everywhere — the first is a context-window problem, the second is a model
    problem, and they have different fixes.
    """
    order: list[tuple[str, str]] = []
    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row.candidate_id, row.dimension or "unlabelled")
        if key not in groups:
            order.append(key)
            groups[key] = _empty()
        _absorb(groups[key], row)
    out = []
    for key in order:
        one = _finish(groups[key])
        one["candidate"] = key[0]
        one["dimension"] = key[1]
        out.append(one)
    return out


def by_case(rows: list) -> list[dict]:
    """One row per (candidate, case): the evidence behind every aggregate.

    Printed in the report's detail section so a surprising score can be checked
    against the answer that produced it, rather than taken on trust.
    """
    out = []
    for row in rows:
        one = row.as_dict()
        one["found"] = list(row.score.get("found") or [])
        one["missed"] = list(row.score.get("missed") or [])
        one["hallucinated"] = list(row.score.get("hallucinated") or [])
        one["spec_missed"] = list(row.score.get("spec_missed") or [])
        one["spec_errors"] = list(row.score.get("spec_errors") or [])
        out.append(one)
    return out


def summary(rows: list) -> dict:
    """What this sweep is, for the head of the report.

    Comparability is checked the only way it can be: **per case**. Different
    cases have different prompts by design, so a sweep of ten cases has ten
    fingerprints and that is correct. What must never happen is one case
    reaching two candidates as two different briefs — that is the failure a
    fingerprint is here to catch, and a check that compared fingerprints across
    cases instead would cry wolf on every honest run.
    """
    per_case: dict[str, set[str]] = {}
    for row in rows:
        if not row.case_id or not row.prompt_fingerprint:
            continue
        per_case.setdefault(row.case_id, set()).add(row.prompt_fingerprint)
    cases = sorted(per_case)
    sets = sorted({(row.set_id, row.set_version) for row in rows if row.set_id})
    split = [name for name in cases if len(per_case[name]) > 1]
    return {
        "runs": len(rows),
        "candidates": sorted({row.candidate_id for row in rows if row.candidate_id}),
        "cases": cases,
        "case_count": len(cases),
        "sets": [{"set_id": one[0], "set_version": one[1]} for one in sets],
        # One fingerprint per case: `{case_id: sha}` for a reader who wants to
        # re-derive it, and the list of cases that disagree.
        "case_fingerprints": {name: sorted(per_case[name])[0] for name in cases},
        "cases_with_split_briefs": split,
        "fingerprints_agree": not split,
        "graded_runs": sum(1 for row in rows if row.graded),
        "failed_runs": sum(1 for row in rows if row.failed),
    }
