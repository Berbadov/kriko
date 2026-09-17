"""One dial, and what it is likely to cost.

"Fifteen sources burn far more tokens than three. That decision belongs to me,
per run." It already did — `max_documents`, `budget_usd`, `context_chars`,
`batch_size` were all settable — which is the problem: five numbers with no
visible relationship, and no answer to the only question being asked.
"""

import pytest

from app import scale
from app.web import state


@pytest.fixture
def conn(tmp_path):
    handle = state.connect(tmp_path / "app.sqlite")
    yield handle
    handle.close()


# ── the dial ─────────────────────────────────────────────────────────────

def test_each_preset_reads_more_than_the_one_below_it():
    depths = [scale.applied(one, {})["max_documents"]
              for one in ("quick", "standard", "deep")]
    assert depths == sorted(depths) and len(set(depths)) == 3


def test_a_deeper_preset_also_reads_more_of_each_page():
    """A Deep run that truncated every source at a Quick run's length would
    cost more for the same blindness."""
    quick = scale.applied("quick", {})
    deep = scale.applied("deep", {})
    assert deep["context_chars"] > quick["context_chars"]


def test_the_careful_end_stops_batching():
    """Batching is cheaper and makes grounding harder, so depth unbatches."""
    assert scale.applied("deep", {})["batch_size"] == 1
    assert scale.applied("quick", {})["batch_size"] > 1


def test_a_preset_carries_its_own_ceiling():
    """A Deep run stopped at a Quick run's cap is a reader refused the depth
    they chose; a Quick run given a Deep run's cap is a cap doing nothing."""
    assert (scale.applied("deep", {})["cap_usd"]
            > scale.applied("quick", {})["cap_usd"])


# ── and what it must not do ──────────────────────────────────────────────

def test_an_explicit_number_still_wins_over_the_preset():
    """The dial is a bundle of these knobs, never a wall around them."""
    assert scale.applied("quick", {"max_documents": 11})["max_documents"] == 11


def test_an_unknown_scale_runs_at_the_default_rather_than_refusing():
    """An older client, a stored request, a typo. None of them is an error."""
    assert scale.applied("enormous", {})["scale"] == scale.DEFAULT
    assert scale.applied("", {})["scale"] == scale.DEFAULT


def test_custom_with_no_numbers_still_reads_something():
    """Zero everywhere would be a run that reads nothing at all."""
    depth = scale.applied("custom", {})
    assert depth["max_documents"] > 0
    assert depth["context_chars"] > 0


def test_custom_is_the_same_code_path_as_every_other_preset():
    depth = scale.applied("custom", {"max_documents": 25, "cap_usd": 9.0})
    assert depth["max_documents"] == 25
    assert depth["cap_usd"] == 9.0


# ── the estimate ─────────────────────────────────────────────────────────

def test_an_installation_that_has_measured_nothing_says_so(conn):
    """An estimate is a promise about somebody's money. One the app cannot
    keep is worse than none."""
    guess = scale.estimate(conn, "deep")
    assert guess["usd"] is None
    assert guess["tokens"] is None
    assert "measured" in guess["note"]


def _measured(conn, runs=3, usd=0.20, tokens=10_000):
    """Runs this installation actually paid for — the only basis for an estimate."""
    for n in range(runs):
        state.open_research_run(conn, f"run-{n}", plane="api", model="m")
        state.close_research_run(conn, f"run-{n}", "ok",
                                 spent_usd=usd, tokens_used=tokens)


def test_the_estimate_scales_with_depth_once_there_is_something_to_scale(conn):
    _measured(conn)
    quick = scale.estimate(conn, "quick")
    deep = scale.estimate(conn, "deep")
    assert quick["usd"] is not None, "three measured runs is a basis"
    assert deep["usd"] > quick["usd"]
    assert deep["tokens"] > quick["tokens"]
    assert deep["sources"] > quick["sources"]


def test_the_estimate_says_it_came_from_measurement_not_a_price_list(conn):
    _measured(conn)
    assert "measured" in scale.estimate(conn, "standard")["note"]
    assert scale.estimate(conn, "standard")["basis"] >= 2


def test_one_run_is_an_anecdote_and_does_not_become_an_estimate(conn):
    """The same rule `app/costs.py` applies: an average from one run is a guess
    wearing a decimal point."""
    _measured(conn, runs=1)
    assert scale.estimate(conn, "deep")["usd"] is None


def test_every_position_is_offered_with_its_numbers(conn):
    offered = scale.offered(conn)
    assert [one["id"] for one in offered] == [
        "quick", "standard", "deep", "custom"]
    assert all(one["note"] for one in offered), (
        "a preset described in the client is one that drifts from its numbers")


# ── the ceiling ──────────────────────────────────────────────────────────

def test_a_run_under_its_cap_is_told_nothing():
    assert scale.warning(0.10, 1.00) == ""


@pytest.mark.parametrize("spent", [0.55, 0.85])
def test_a_run_approaching_its_cap_is_warned_before_it_stops(spent):
    """The difference between "this is going to be expensive" and "this is
    about to stop" is the difference between a decision and a notification."""
    said = scale.warning(spent, 1.00)
    assert "cap" in said and "%" in said


def test_hitting_the_cap_says_it_stopped_rather_than_that_it_failed():
    assert "stopped" in scale.warning(1.20, 1.00)
    assert scale.over_cap(1.20, 1.00)


def test_no_cap_means_no_cap():
    assert scale.over_cap(99.0, 0.0) is False
    assert scale.warning(99.0, 0.0) == ""


# ── and the thing a dial must never do ──────────────────────────────────

def test_a_run_that_names_no_scale_keeps_the_budget_it_always_had():
    """A choice nobody made must not cost anybody money.

    Letting the default preset's ceiling apply to every unscaled run would
    have raised the standing per-subject budget five-fold for every caller
    that never asked for a dial — the agenda among them.
    """
    from app.web import tasks

    assert tasks._budget({"backend": "api"}) == tasks.DEFAULT_BUDGET_USD


def test_naming_a_scale_is_what_brings_its_ceiling():
    from app.web import tasks

    assert tasks._budget({"backend": "api", "scale": "deep"}) == 3.0
    # And an explicit number still beats the preset.
    assert tasks._budget(
        {"backend": "api", "scale": "deep", "budget_usd": 0.05}) == 0.05
