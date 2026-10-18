"""Scoring one answer: quality from an answer key, cost from a meter.

Every number in the report is computed here, once. The old benchmark computed
the same rate in three places — `gold.judge`, `precisionbench.judge`, and again
inside `protocols._readout_one` — and three formulas for one fact is how a
table ends up disagreeing with itself.

**Quality is mechanical.** `app.precisionbench.judge` does the comparing: a
quote must be a real span of the document at the URL the answer named, a fact
must clear the case's own term groups, a specification must match the key's
name, value and URL exactly. No model is asked to grade another model, because
a model asked to score a peer agrees with it far too often to be evidence, and
the one thing this must be is independent of what it measures.

**Cost is whatever was actually counted.** `sockets.py` decides whether a
count is `reported`, `reported_total`, `estimated` or absent; this module only
does arithmetic on it, and refuses to fold an estimate into a measured mean.

The four numbers the model choice turns on, and why each is its own column:

* **recall** — share of the case's expected facts that were found. A model that
  answers nothing scores zero here and well everywhere else, which is the whole
  point of keeping it separate.
* **hallucination rate** — share of *produced* items that the key could not
  support: an invented quote, a claim the documents do not make, a
  specification the answer got wrong. Reported apart from recall because the
  remedies differ — low recall is a better brief, hallucination is a model not
  to trust unattended.
* **tokens** — in, out and total, plus **tokens per expected fact found**,
  which is the only cost figure that punishes both overspending and
  under-delivering. A cheap model that finds nothing does not win on it.
* **abstention** — whether a case with no answer in it produced an empty answer
  instead of a plausible invention. On the phone this is the safety property,
  so it is a column and not a footnote.
"""

from app import gold

#: The fields of a verdict that are part of this benchmark's contract. A stable
#: list rather than whatever `judge` happens to return, so the report cannot
#: silently gain or lose a column when the judge grows a field.
VERDICT_KEYS = (
    "recall", "spec_recall", "abstention_correct", "pass", "valid_shape",
    "produced", "fabricated", "unsupported_quotes", "hallucination_rate",
    "found", "missed", "hallucinated", "spec_found", "spec_missed",
    "spec_errors", "errors",
)


def verdict(case: dict, reply: str, sources: dict[str, str]) -> dict:
    """One answer, scored against one case's key.

    A reply that is not JSON at all scores as produced=0 and pass=False rather
    than raising: answering in prose is a failure mode this exists to count,
    and a benchmark that crashed on it would only ever measure tidy models.
    """
    from app import precisionbench

    try:
        judged = precisionbench.judge(case, reply or "", sources or {})
    except Exception as exc:  # noqa: BLE001 — an unreadable answer is a score
        judged = {
            "errors": [{"reason": f"unreadable-answer: {type(exc).__name__}"}],
            "raw_produced": 0, "unsupported_quotes": 0, "valid_shape": False,
            "found": [], "missed": [one.get("id", "") for one in case.get("supported") or []],
            "hallucinated": [], "spec_found": [], "spec_missed": [],
            "spec_errors": [], "abstention_correct": None,
            "abstention_expected": bool(case.get("expect_abstention")),
            "pass": False, "recall": None, "hallucination_rate": None,
        }

    wanted = len(case.get("supported") or [])
    found = list(judged.get("found") or [])
    produced = int(judged.get("raw_produced") or 0)
    fabricated = len(judged.get("errors") or [])
    specs_wanted = list(case.get("expected_specs") or [])
    spec_found = list(judged.get("spec_found") or [])
    spec_errors = list(judged.get("spec_errors") or [])
    # How many specifications the model actually put forward. `judge` reports
    # the wrong ones and the right ones separately, so the denominator has to be
    # reassembled: without it a model that returns no figures at all would have
    # no wrong-spec rate and would read as careful.
    spec_produced = len(spec_found) + len(spec_errors)
    return {
        "recall": judged.get("recall"),
        "spec_recall": (round(len(set(spec_found)) / len(specs_wanted), 3)
                        if specs_wanted else None),
        "abstention_correct": judged.get("abstention_correct"),
        "pass": bool(judged.get("pass")),
        "valid_shape": bool(judged.get("valid_shape")),
        "produced": produced,
        "fabricated": fabricated,
        "unsupported_quotes": int(judged.get("unsupported_quotes") or 0),
        "hallucination_rate": (round(fabricated / produced, 3)
                               if produced else None),
        "found": found,
        "missed": list(judged.get("missed") or []),
        "hallucinated": list(judged.get("hallucinated") or []),
        "spec_found": spec_found,
        "spec_missed": list(judged.get("spec_missed") or []),
        "spec_errors": spec_errors,
        "errors": list(judged.get("errors") or []),
        # Not part of VERDICT_KEYS' contract but read by the aggregate: the two
        # denominators, so a rate can be *pooled* across cases rather than
        # averaged from rates. A mean of rates lets a one-fact case outvote a
        # four-fact one.
        "wanted": wanted,
        "specs_wanted": len(specs_wanted),
        "specs_produced": spec_produced,
    }


def tokens_per_fact(reply, score: dict) -> float | None:
    """Tokens spent per expected fact found. `None` when nothing was found.

    `None` and not infinity, and not the total either: a model that found
    nothing has no cost per find, and printing its raw spend in this column
    would rank it *best* for having failed cheapest.

    Only metered tokens count. An `estimated` reply returns `None` here so a
    guessed number can never decide which model is efficient.
    """
    if not reply.metered or reply.tokens_total is None:
        return None
    found = len(score.get("found") or [])
    if found <= 0:
        return None
    return round(reply.tokens_total / found, 1)


def rate(hits: int, total: int) -> float | None:
    """A share, or `None` where there was nothing to divide by.

    `None` rather than `0.0`: "found none of two" and "there were none to find"
    are different facts, and a benchmark that prints both as 0.0 teaches its
    reader to distrust the column.
    """
    if total <= 0:
        return None
    return round(hits / total, 3)


def interval(hits: int, total: int):
    """The 95% interval on a rate — `app.gold.wilson`, the one this codebase has.

    Because n=3 is an anecdote, and two models at "60%" from five findings and
    from two hundred are not the same fact.
    """
    return gold.wilson(hits, total)
