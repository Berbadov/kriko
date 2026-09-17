"""What a run is spending, while it spends it.

"I want to see spend as it happens, not discover it afterwards." The app
already recorded what a run cost — `research_runs` carries dollars and tokens —
but only on the way out, as one number for the whole run. Which is the wrong
shape twice over: it arrives too late to act on, and one opaque total cannot
answer the question a reader actually has, which is *what is expensive here*.

So: a tally per stage and per model, added to as the run goes, readable at any
moment.

**Two currencies, and they are not interchangeable.** Tokens are measured;
dollars are *derived*, from `models.toml`, which the reader owns and may have
left blank. A model with no row meters its tokens and reports no cost — and the
run says "cost unknown" rather than zero, because a run reported as free is a
run somebody will repeat.

**Nothing here estimates.** `app/scale.py` estimates, before a run, and labels
it. This is the other thing: what was actually consumed. Mixing them would put
a guess and a measurement in the same column, and the reader's next decision is
whether to spend more.

**A stage is a stage of work, not a model.** The same model may be used by two
stages and two models by one stage, so the tally is keyed by both — which is
what makes "extraction is where the money goes" a thing the screen can say.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Meter:
    """The running total for one run, by stage and by model.

    Deliberately not thread-safe and deliberately not a singleton. A run is one
    job on one worker (`app/web/jobs.py` runs a single worker on purpose), and
    a shared meter would be the one place two runs could silently bill each
    other.
    """

    home: Path | None = None
    #: `(stage, model) -> {tokens_in, tokens_out, calls}`.
    rows: dict[tuple[str, str], dict] = field(default_factory=dict)
    #: The ceiling this run was given, in dollars. 0 means uncapped.
    cap_usd: float = 0.0
    #: Thresholds already announced, so a warning is said once rather than on
    #: every call after it is crossed. A meter that repeats itself is a meter
    #: people mute.
    _warned: set = field(default_factory=set)
    #: The last totals read off each completer, per `(stage, model)`. The
    #: adapters accumulate across a whole run, so their attributes are totals
    #: and this is what turns them back into the per-call deltas a tally wants.
    _seen: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)

    def add(self, stage: str, model: str, *, tokens_in=None, tokens_out=None) -> None:
        """One call's worth. `None` is "nobody counted", and stays that way."""
        row = self.rows.setdefault(
            (stage or "", model or ""),
            {"tokens_in": None, "tokens_out": None, "calls": 0},
        )
        row["calls"] += 1
        for key, value in (("tokens_in", tokens_in), ("tokens_out", tokens_out)):
            if isinstance(value, int) and not isinstance(value, bool):
                row[key] = (row[key] or 0) + value

    def observe(self, stage: str, complete) -> None:
        """Read a completer's own running totals into the meter.

        Duck-typed, like every other provenance read in this codebase: a plane
        that counts reports numbers and one that does not leaves them None. The
        deltas are computed here because the adapters accumulate — they are
        reused across a run, so their attributes are totals rather than
        per-call figures.
        """
        model = str(getattr(complete, "model", "") or "")
        before = self._seen.get((stage, model), (0, 0))
        now = (int(getattr(complete, "tokens_in", None) or 0),
               int(getattr(complete, "tokens_out", None) or 0))
        self._seen[(stage, model)] = now
        self.add(stage, model,
                 tokens_in=now[0] - before[0] or None,
                 tokens_out=now[1] - before[1] or None)

    # ── what it adds up to ───────────────────────────────────────────────

    def cost(self, stage: str, model: str) -> float | None:
        from app import modelcatalogue

        row = self.rows.get((stage, model))
        if not row or row["tokens_in"] is None and row["tokens_out"] is None:
            return None
        return modelcatalogue.price(
            model, row["tokens_in"] or 0, row["tokens_out"] or 0, self.home)

    @property
    def usd(self) -> float | None:
        """The run's cost, or `None` when any part of it is unpriceable.

        `None` rather than "the priceable part", because a partial total
        presented as a total is the more dangerous of the two errors: it reads
        as cheap. `breakdown()` shows which rows are missing a price so the
        reader can add a row and get a real number.
        """
        priced = [self.cost(*key) for key in self.rows]
        if not priced or any(one is None for one in priced):
            return None
        return round(sum(one or 0.0 for one in priced), 6)

    @property
    def tokens(self) -> int:
        return sum((row["tokens_in"] or 0) + (row["tokens_out"] or 0)
                   for row in self.rows.values())

    def breakdown(self) -> list[dict]:
        """Every (stage, model) pair, most expensive first, unpriced last.

        Sorted by cost rather than by stage order, because the question this
        answers is "what is expensive here" and the answer should be the first
        row rather than something to scan for.
        """
        out = []
        for (stage, model), row in self.rows.items():
            cost = self.cost(stage, model)
            out.append({
                "stage": stage, "model": model, "calls": row["calls"],
                "tokens_in": row["tokens_in"], "tokens_out": row["tokens_out"],
                "usd": round(cost, 6) if cost is not None else None,
                "priced": cost is not None,
            })
        out.sort(key=lambda one: (one["usd"] is None, -(one["usd"] or 0.0),
                                  one["stage"], one["model"]))
        return out

    # ── and what it says out loud ────────────────────────────────────────

    def crossed(self) -> str:
        """A threshold warning, once, or "" — see `app/scale.WARN_AT`.

        Silent where the cost is unknown: a cap cannot be enforced against a
        number nobody has, and inventing one to warn about would be worse than
        the silence.
        """
        from app import scale

        spent = self.usd
        if spent is None or not self.cap_usd:
            return ""
        for mark in sorted((*scale.WARN_AT, 1.0), reverse=True):
            if spent / self.cap_usd >= mark and mark not in self._warned:
                self._warned.add(mark)
                return scale.warning(spent, self.cap_usd)
        return ""

    def over_cap(self) -> bool:
        from app import scale

        spent = self.usd
        return spent is not None and scale.over_cap(spent, self.cap_usd)

    def snapshot(self) -> dict:
        """The whole tally, for the job row a screen is polling.

        One object rather than a stream of deltas: the reader may open the
        screen halfway through, and a view that could only be built from every
        event since the start is a view that is wrong for anyone who arrived
        late.
        """
        return {
            "tokens": self.tokens,
            "usd": self.usd,
            "cap_usd": self.cap_usd or None,
            "share_of_cap": (
                round(self.usd / self.cap_usd, 4)
                if self.usd is not None and self.cap_usd else None
            ),
            "by_stage": self.breakdown(),
            # Said rather than inferred from a null: "nothing was counted" and
            # "it was free" look identical in a number and must not.
            "unpriced": [
                f"{one['stage']}/{one['model']}"
                for one in self.breakdown() if not one["priced"]
            ],
        }
