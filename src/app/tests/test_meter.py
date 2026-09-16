"""Spend as it happens, not discovered afterwards.

The app already recorded what a run cost — on the way out, as one number. Wrong
shape twice: too late to act on, and one opaque total cannot answer the question
a reader has, which is *what is expensive here*.
"""

import pytest

from app.meter import Meter


def _run(cap=0.0):
    return Meter(cap_usd=cap)


# ── two currencies, and they are not interchangeable ────────────────────

def test_tokens_are_counted_per_stage_and_per_model():
    """The same model may serve two stages and two models one stage."""
    m = _run()
    m.add("extract", "gpt-4o-mini", tokens_in=1000, tokens_out=200)
    m.add("extract", "gpt-4o-mini", tokens_in=500, tokens_out=100)
    m.add("synthesise", "claude-opus-5", tokens_in=2000, tokens_out=400)

    rows = {(one["stage"], one["model"]): one for one in m.breakdown()}
    assert rows[("extract", "gpt-4o-mini")]["tokens_in"] == 1500
    assert rows[("extract", "gpt-4o-mini")]["calls"] == 2
    assert rows[("synthesise", "claude-opus-5")]["tokens_out"] == 400


def test_cost_is_derived_from_the_catalogue_not_from_the_total():
    """Input and output cost different amounts, so a total cannot be priced."""
    m = _run()
    m.add("extract", "claude-opus-5", tokens_in=1_000_000, tokens_out=0)
    cheap = m.usd
    other = _run()
    other.add("extract", "claude-opus-5", tokens_in=0, tokens_out=1_000_000)
    assert other.usd > cheap, "output is the expensive half and must price higher"


def test_the_most_expensive_stage_is_the_first_row():
    """"What is expensive here" should be the answer, not something to scan for."""
    m = _run()
    m.add("plan", "claude-haiku-4-5", tokens_in=1000, tokens_out=100)
    m.add("synthesise", "claude-opus-5", tokens_in=100_000, tokens_out=20_000)
    assert m.breakdown()[0]["stage"] == "synthesise"


# ── what it must never claim ────────────────────────────────────────────

def test_a_model_with_no_row_meters_its_tokens_and_reports_no_cost():
    m = _run()
    m.add("extract", "some-local-llama", tokens_in=5000, tokens_out=500)
    assert m.tokens == 5500
    assert m.usd is None, "a run reported as free is a run somebody repeats"
    assert m.breakdown()[0]["priced"] is False


def test_a_partly_priced_run_reports_no_total_rather_than_a_low_one():
    """A partial total presented as a total reads as cheap — the more
    dangerous of the two errors."""
    m = _run()
    m.add("extract", "gpt-4o-mini", tokens_in=1000, tokens_out=100)
    m.add("synthesise", "mystery-model", tokens_in=1000, tokens_out=100)
    assert m.usd is None
    assert m.snapshot()["unpriced"] == ["synthesise/mystery-model"]


def test_nobody_counted_is_not_the_same_as_it_was_free():
    m = _run()
    m.add("extract", "gpt-4o-mini")
    assert m.breakdown()[0]["tokens_in"] is None
    assert m.usd is None


# ── the ceiling ─────────────────────────────────────────────────────────

def test_a_threshold_is_announced_once_rather_than_on_every_call():
    """A meter that repeats itself is a meter people mute."""
    m = _run(cap=1.00)
    m.add("extract", "claude-opus-5", tokens_in=100_000, tokens_out=0)  # $0.50
    assert "cap" in m.crossed()
    assert m.crossed() == "", "already said"


def test_crossing_a_higher_threshold_is_said_even_after_a_lower_one():
    m = _run(cap=1.00)
    m.add("extract", "claude-opus-5", tokens_in=100_000, tokens_out=0)
    assert m.crossed()
    m.add("extract", "claude-opus-5", tokens_in=70_000, tokens_out=0)
    assert m.crossed(), "80% is news even after 50% was announced"


def test_a_cap_cannot_be_enforced_against_a_cost_nobody_has():
    """Inventing a number to warn about would be worse than the silence."""
    m = _run(cap=0.01)
    m.add("extract", "mystery-model", tokens_in=10_000_000, tokens_out=0)
    assert m.crossed() == ""
    assert m.over_cap() is False


def test_an_uncapped_run_is_metered_and_never_warned():
    m = _run(cap=0.0)
    m.add("extract", "claude-opus-5", tokens_in=1_000_000, tokens_out=1_000_000)
    assert m.usd > 0
    assert m.crossed() == ""
    assert m.over_cap() is False


def test_going_over_says_so():
    m = _run(cap=0.10)
    m.add("extract", "claude-opus-5", tokens_in=1_000_000, tokens_out=0)  # $5
    assert m.over_cap()
    assert "stopped" in m.crossed()


# ── the shape a screen polls ────────────────────────────────────────────

def test_the_snapshot_is_whole_rather_than_a_stream_of_deltas():
    """The reader may open the screen halfway through."""
    m = _run(cap=2.00)
    m.add("extract", "claude-opus-5", tokens_in=200_000, tokens_out=0)
    shot = m.snapshot()
    assert shot["tokens"] == 200_000
    assert shot["usd"] == pytest.approx(1.0)
    assert shot["share_of_cap"] == pytest.approx(0.5)
    assert shot["by_stage"]


def test_an_adapters_running_totals_are_read_as_deltas():
    """The adapters accumulate across a run, so their attributes are totals."""
    class Fake:
        model = "gpt-4o-mini"
        tokens_in = 100
        tokens_out = 10

    m, fake = _run(), Fake()
    m.observe("extract", fake)
    fake.tokens_in, fake.tokens_out = 250, 30      # one more call happened
    m.observe("extract", fake)

    row = m.breakdown()[0]
    assert row["tokens_in"] == 250, "totals, not 100 + 250"
    assert row["calls"] == 2
