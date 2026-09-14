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

#: The named protocols, narrowest first. A closed engineering vocabulary — the
#: rule against hand-enumerated lists is about data that grows with pack
#: coverage, and this is three settings of one dial.
#:
#: `narrow` exists for a model that cannot hold a batch at all; `wide` is worth
#: four times fewer calls when a model can take it. Nothing picks either
#: without evidence.
CATALOGUE = (
    Spend(name="narrow", context_chars=6000, batch_size=1),
    STANDARD,
    Spend(name="wide", context_chars=10000, batch_size=4),
)

BY_NAME = {one.name: one for one in CATALOGUE}

#: How many measured runs a protocol needs before it may be chosen over the
#: default. Two is not statistics; it is the difference between "it worked
#: once" and "it worked", and the alternative — one lucky run promoting a
#: protocol for good — is how a benchmark starts lying.
MIN_RUNS = 2

#: And how much better it has to be. A protocol that keeps the same proportion
#: of findings for fewer calls is a win; one that keeps three percent more is
#: noise, and swapping on noise makes every later measurement harder to read.
MIN_MARGIN = 0.05


def score(row: dict) -> float | None:
    """What a measured protocol was worth, or `None` if it cannot be judged.

    The acceptance rate, not the finding count: a run that returns thirty
    findings and keeps two is worse than one that returns four and keeps three,
    and this is the number that says so. A protocol whose runs mostly *failed*
    scores nothing at all — a plane that cannot finish is not a cheap plane.
    """
    runs = int(row.get("runs") or 0)
    if runs < MIN_RUNS:
        return None
    if int(row.get("failures") or 0) * 2 > runs:
        return None
    rate = row.get("acceptance")
    return float(rate) if isinstance(rate, (int, float)) else None


def choose(summary: list[dict], model: str) -> Spend:
    """The protocol to use for `model`, given this installation's measurements.

    Two rules, and the second is the one that keeps this honest:

    * **The default has to have been measured too.** A candidate is compared
      against `STANDARD`'s own score on the same model, never against nothing.
      Without that rule a single mediocre measurement of one protocol would
      promote it — the reasoning being "it is the only one we have", which is
      how a benchmark comes to recommend the only thing anybody bothered to
      run.
    * **Ties and near-ties go to the cheaper protocol** — the one with the
      larger batch. When two settings keep the same proportion of findings, the
      one making fewer calls is strictly better, and the margin has already
      decided the difference is not real.
    """
    if not model:
        return STANDARD
    judged = {}
    for row in summary:
        if (row.get("model") or "") != model:
            continue
        spend = BY_NAME.get(row.get("protocol") or "")
        value = score(row)
        if spend is None or value is None:
            continue
        judged[spend.name] = (value, spend)
    baseline = judged.get(STANDARD.name)
    if baseline is None:
        return STANDARD
    contenders = [
        spend for value, spend in judged.values() if value >= baseline[0] - MIN_MARGIN
    ]
    return max(contenders, key=lambda spend: (spend.batch_size, spend.context_chars))


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
