"""Choosing how an operation spends a model — from measurements, not opinion.

B123. A **protocol** (`kriko.research.Spend`) is how much of a document goes
into one call and how many documents go into one call. The failure it governs
is two-sided and the middle is narrow:

* **Too little batching burns tokens.** The brief, the pack's principle and the
  vocabulary are re-sent for every document, and most of what is paid for is
  the same paragraph over and over.
* **Too much piles context until the model stops quoting and starts
  composing.** Kriko catches that at the grounding gate — so the batch is
  *refused* and the tokens are spent anyway. A protocol that is too wide is
  therefore worse than one that is too narrow: it costs the same money and
  produces nothing.

Which means the right setting is a property of **the model**, not of the
operation: *this one holds together under N characters at that batch size; that
one takes more.* That is a ratio, and a ratio is a measurement or it is a guess.
So this module does not contain a table of models. It contains a rule for
reading `bench_runs` (B111) and a conservative default for a model nobody has
measured yet.

**Why the picking is here and the shape is in `kriko/`.** The engine may not
import the interface, and choosing means reading this installation's own
benchmark rows, which are interface state. So `kriko/research/base.py` defines
what a protocol is and every researcher takes one as an argument; this decides
which. Same split `app/providers/` makes for sockets.

**It fails towards the known-good.** With no measurements, or too few to mean
anything, the answer is `STANDARD` — the behaviour that existed before
protocols did. A mechanism for going faster must never make a fresh install
slower or wronger than it was.
"""

from kriko.research.base import STANDARD, Spend

#: The named protocols. A closed engineering vocabulary — the rule against
#: hand-enumerated lists is about data that grows with pack coverage, and this
#: is two dials (context/batch, and now the preamble) crossed a few times, not
#: catalog data.
#:
#: `narrow` exists for a model that cannot hold a batch at all; `wide` is worth
#: four times fewer calls when a model can take it. The `-principled` and
#: `-worked-example` variants are the same geometry under the other named
#: preamble (B126 §7) — the axis "nobody can guess", so it has to be a real
#: named row a benchmark can pick, not a constant baked into the prompt.
#: Nothing picks any of them without evidence.
CATALOGUE = (
    Spend(name="narrow", context_chars=6000, batch_size=1),
    STANDARD,
    Spend(name="wide", context_chars=10000, batch_size=4),
    Spend(name="standard-principled", context_chars=12000, batch_size=1,
          preamble="principled"),
    Spend(name="wide-principled", context_chars=10000, batch_size=4,
          preamble="principled"),
    Spend(name="standard-worked-example", context_chars=12000, batch_size=1,
          preamble="worked-example"),
)

BY_NAME = {one.name: one for one in CATALOGUE}

#: How many measured runs a protocol needs before it may be chosen over the
#: default. Two is not statistics; it is the difference between "it worked
#: once" and "it worked", and the alternative — one lucky run promoting a
#: protocol for good — is how a benchmark starts lying.
MIN_RUNS = 2


def _wilson(hits: int, total: int) -> tuple[float, float] | None:
    """Delegates to `app.gold.wilson` — the one interval this codebase has.

    Imported at call time rather than at module load: `app/gold.py` is the
    module that knows what a rate *means* here (B126), and importing it up top
    would make every caller of `app/protocols.py` — including the ordinary
    research path — pull in the gold-set loader for no reason.
    """
    from app import gold

    return gold.wilson(hits, total)


def choose(summary: list[dict], model: str) -> Spend:
    """The protocol to use for `model`, given this installation's measurements.

    Replaces a flat `MIN_MARGIN` with a Wilson score interval on each
    protocol's acceptance rate (B126 §5/§9): "kept 60% of 5" and "kept 60% of
    200" are different facts, and a fixed 5% margin could not tell them apart
    — a decision from two runs must be able to say *not yet measured* rather
    than pretending a coin flip settled anything.

    Two rules:

    * **The default has to have been measured too.** A candidate is judged
      against `STANDARD`'s own interval on the same model, never against
      nothing — without that rule a single measurement of one protocol would
      promote it, "it is the only one we have" being how a benchmark comes to
      recommend the only thing anybody bothered to run.
    * **A protocol is only excluded when it is *provably* worse** — its
      interval's upper bound below some other protocol's lower bound, meaning
      the two do not overlap and the other one is genuinely ahead. Among
      whatever survives that filter, the cheaper or bigger-batch protocol
      wins: an interval that merely looks a little lower is exactly the
      "three percent more is noise" case the old margin existed to catch, and
      an overlapping interval says so honestly instead of by a guessed
      threshold.
    """
    if not model:
        return STANDARD
    judged: dict[str, tuple[tuple[float, float], Spend]] = {}
    for row in summary:
        if (row.get("model") or "") != model:
            continue
        spend = BY_NAME.get(row.get("protocol") or "")
        if spend is None:
            continue
        runs = int(row.get("runs") or 0)
        if runs < MIN_RUNS:
            continue
        if int(row.get("failures") or 0) * 2 > runs:
            continue
        accepted = int(row.get("accepted") or 0)
        refused = int(row.get("refused") or 0)
        kept = accepted + refused
        interval = _wilson(accepted, kept) if kept else None
        if interval is None:
            continue
        judged[spend.name] = (interval, spend)

    baseline = judged.get(STANDARD.name)
    if baseline is None:
        # Not yet measured, honestly: `STANDARD` is the answer with no
        # evidence *for it specifically*, exactly as it was before any
        # protocol existed.
        return STANDARD

    survivors = []
    for name, (interval, spend) in judged.items():
        lo, hi = interval
        beaten = any(
            other_lo > hi
            for other_name, (other_interval, _) in judged.items()
            if other_name != name
            for other_lo, _other_hi in [other_interval]
        )
        if not beaten:
            survivors.append(spend)
    # `STANDARD` is always in `judged` here (the baseline check above), so
    # `survivors` can never be empty.
    return max(survivors, key=lambda spend: (spend.batch_size, spend.context_chars))


def spend_for(app_state_path, model: str) -> Spend:
    """`choose`, against the rows this installation has actually measured.

    Silent on failure and `STANDARD` on any doubt: a missing or unreadable
    benchmark table is a reason to use the known-good setting, never a reason a
    research run does not start.
    """
    try:
        from app.web import state

        conn = state.connect(app_state_path)
        try:
            return choose(state.bench_summary(conn), model)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — see the docstring
        return STANDARD


def readout(raw_rows: list[dict], summary: list[dict]) -> list[dict]:
    """Measured quality and resources per set/version/plane/model/protocol/search.

    Unknown spend and partial token usage never become zero. Failed attempts
    contribute latency and reported spend, but do not pretend to be graded
    answers. ``summary`` remains accepted for callers of the older interface.
    """
    # B185: runs scored on different test sets are never ranked together.
    # Each set gets its own rows, labelled with the set it measured, and an
    # empty set id is its own partition (a pack-derived run never mixes with
    # a fixed-set one).
    def _set_of(row: dict) -> tuple[str, str]:
        return (str(row.get("set_id") or ""), str(row.get("set_version") or ""))

    out = []
    seen_sets: list[tuple[str, str]] = []
    for row in raw_rows:
        key = _set_of(row)
        if key not in seen_sets:
            seen_sets.append(key)
    for set_key in seen_sets:
        out += _readout_one(
            [row for row in raw_rows if _set_of(row) == set_key], summary, set_key)
    return out


def _readout_one(raw_rows: list[dict], summary: list[dict],
                 set_key: tuple[str, str] = ("", "")) -> list[dict]:
    import math
    import statistics

    configurations = sorted({
        (str(row.get("model") or ""), str(row.get("plane") or ""),
         str(row.get("protocol") or STANDARD.name),
         str(row.get("search_provider") or ""))
        for row in raw_rows if row.get("model")})
    out = []
    for model, plane, protocol, search in configurations:
        spend = BY_NAME.get(protocol)
        mine = [row for row in raw_rows if (row.get("model") or "") == model
                and (row.get("plane") or "") == plane
                and (row.get("protocol") or STANDARD.name) == protocol
                and (row.get("search_provider") or "") == search]
        graded = [row for row in mine if row.get("gold") and not row.get("error")]
        hallucinated = sum(
            len((row.get("gold") or {}).get("hallucinated") or []) for row in graded
        )
        produced = sum(int((row.get("gold") or {}).get(
            "raw_produced", row.get("findings") or row.get("accepted") or 0))
            for row in graded)
        found = sum(len(row["gold"].get("found") or []) for row in graded)
        wanted = found + sum(len(row["gold"].get("missed") or []) for row in graded)
        priced = [row for row in mine if row.get("usd") is not None]
        usd_total = sum(float(row["usd"]) for row in priced)
        priced_accepted = sum(int(row.get("accepted") or 0) for row in priced)
        counted = [row for row in mine if row.get("tokens") is not None and
                   (row.get("measurement") or (row.get("gold") or {}).get("measurement", {})).get("usage_complete") is not False]
        counted_accepted = sum(int(row.get("accepted") or 0) for row in counted)
        latencies = sorted(float(row["ms"]) for row in mine if row.get("ms") is not None)
        abstentions = [row["gold"] for row in graded if row["gold"].get("abstention_expected")]
        specs_found = sum(len(row["gold"].get("spec_found") or []) for row in graded)
        specs_wanted = specs_found + sum(len(row["gold"].get("spec_missed") or []) for row in graded)
        measurements = [row.get("measurement") or (row.get("gold") or {}).get("measurement", {})
                        for row in mine]
        out.append({
            "model": model,
            "plane": plane,
            "set_id": set_key[0],
            "set_version": set_key[1],
            "protocol": protocol,
            "batch_size": spend.batch_size if spend else 0,
            "context_chars": spend.context_chars if spend else 0,
            "preamble": spend.preamble if spend else "",
            "search_provider": search,
            # A price only when at least two runs actually counted one — one
            # priced run is an anecdote wearing a decimal point, the same rule
            # `app/costs.py` applies to a spend estimate.
            "usd_per_accepted_claim": (
                round(usd_total / priced_accepted, 4)
                if len(priced) >= MIN_RUNS and priced_accepted else None
            ),
            "hallucination_rate": (
                round(hallucinated / produced, 3) if produced else None
            ),
            "hallucination_interval": (
                _wilson(hallucinated, produced) if produced else None
            ),
            "recall": round(found / wanted, 3) if wanted else None,
            "raw_produced": produced,
            "accepted": sum(int(row.get("accepted") or 0) for row in mine),
            "quote_errors": sum(int(row["gold"].get("unsupported_quotes") or 0) for row in graded),
            "spec_recall": round(specs_found / specs_wanted, 3) if specs_wanted else None,
            "spec_errors": sum(len(row["gold"].get("spec_errors") or []) for row in graded),
            "abstention_accuracy": (round(sum(bool(g.get("abstention_correct")) for g in abstentions)
                                           / len(abstentions), 3) if abstentions else None),
            "passed": sum(row["gold"].get("pass") is True for row in graded),
            "graded_runs": len(graded),
            "failed_runs": sum(bool(row.get("error")) for row in mine),
            "latency_p50_ms": statistics.median(latencies) if latencies else None,
            "latency_p95_ms": latencies[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None,
            "tokens_total": sum(int(row["tokens"]) for row in counted) if counted else None,
            "tokens_mean": round(sum(int(row["tokens"]) for row in counted) / len(counted), 1) if counted else None,
            "counted_runs": len(counted),
            "partial_usage_runs": sum(m.get("usage_complete") is False for m in measurements),
            "tokens_per_accepted_claim": (round(sum(int(row["tokens"]) for row in counted)
                                               / counted_accepted, 1) if counted_accepted else None),
            "tokens_in": sum(m["tokens_in"] for m in measurements if m.get("tokens_in") is not None)
                         if any(m.get("tokens_in") is not None for m in measurements) else None,
            "tokens_out": sum(m["tokens_out"] for m in measurements if m.get("tokens_out") is not None)
                          if any(m.get("tokens_out") is not None for m in measurements) else None,
            "runs": len(mine),
            "note": "" if len(mine) >= MIN_RUNS else (
                "fewer than 2 runs measured for this configuration; repeat before comparing"
            ),
        })
    return out
