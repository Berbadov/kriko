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

from kriko.research.base import PREAMBLES, STANDARD, Spend

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
    """What the sweep is *for*, one row per model (B126 §7/§2 of the design).

    "batch size, context, preamble" is not a screen a reader can act on
    without the two numbers that decide whether to act on it at all: what it
    costs and how often it lies. So this joins the chosen protocol's own
    shape against the gold-graded rows for the same model — `raw_rows` is
    `state.bench_runs()`'s output, which carries each row's `gold` verdict and
    `usd`; `summary` is `state.bench_summary()`, which `choose` already reads.

    One row per model that has *any* measurement, chosen or not: a model with
    fewer than `MIN_RUNS` still belongs on the screen, with `spend` reported
    as `STANDARD` and `note` saying why — "not yet measured" has to be a row a
    reader sees, not a silent gap.
    """
    models = sorted({row.get("model") or "" for row in raw_rows if row.get("model")})
    out = []
    for model in models:
        spend = choose(summary, model)
        mine = [row for row in raw_rows if (row.get("model") or "") == model
                and (row.get("protocol") or STANDARD.name) == spend.name]
        graded = [row for row in mine if row.get("gold")]
        accepted = sum(int(row.get("accepted") or 0) for row in mine)
        hallucinated = sum(
            len((row.get("gold") or {}).get("hallucinated") or []) for row in graded
        )
        priced = [row for row in mine if row.get("usd") is not None]
        usd_total = sum(float(row["usd"]) for row in priced)
        searches = [row.get("search_provider") or "" for row in mine
                    if row.get("search_provider")]
        measured = any(
            (row.get("model") or "") == model
            and (row.get("protocol") or "") == STANDARD.name
            for row in summary
        )
        out.append({
            "model": model,
            "protocol": spend.name,
            "batch_size": spend.batch_size,
            "context_chars": spend.context_chars,
            "preamble": spend.preamble,
            "search_provider": max(set(searches), key=searches.count) if searches else "",
            # A price only when at least two runs actually counted one — one
            # priced run is an anecdote wearing a decimal point, the same rule
            # `app/costs.py` applies to a spend estimate.
            "usd_per_accepted_claim": (
                round(usd_total / accepted, 4)
                if len(priced) >= MIN_RUNS and accepted else None
            ),
            "hallucination_rate": (
                round(hallucinated / accepted, 3) if accepted else None
            ),
            "hallucination_interval": (
                _wilson(hallucinated, accepted) if accepted else None
            ),
            "runs": len(mine),
            "note": "" if measured else (
                "fewer than 2 runs measured for this model — showing the "
                "known-good default, not a chosen protocol"
            ),
        })
    return out
