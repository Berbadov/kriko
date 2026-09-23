"""Scoping a benchmark, and knowing what it costs before pressing.

"Benchmarking everything costs a lot. I need to scope it." Every axis
multiplies — cases × planes × protocols × searches × models × reps — so three
cases, two planes and three protocols at two reps is thirty-six runs, and
nothing on the screen said so.
"""

import pytest

from app import bench
from app.web import state


@pytest.fixture
def conn(tmp_path):
    handle = state.connect(tmp_path / "app.sqlite")
    yield handle
    handle.close()


def _measured(conn, runs=3, usd=0.25, tokens=9000):
    for n in range(runs):
        state.open_research_run(conn, f"r{n}", plane="api", model="m")
        state.close_research_run(conn, f"r{n}", "ok", spent_usd=usd,
                                 tokens_used=tokens)


# ── the grid ─────────────────────────────────────────────────────────────

def test_an_unscoped_grid_is_one_of_everything_not_all_of_it():
    """A benchmark that swept every axis by default is one nobody presses twice."""
    shape = bench.grid({}, case_count=3)
    assert shape["axes"]["protocols"] == 1
    assert shape["axes"]["models"] == 1
    assert shape["runs"] == 3


def test_every_axis_multiplies():
    shape = bench.grid(
        {"planes": "api,harness", "protocols": "a,b,c", "reps": 2}, case_count=3)
    assert shape["runs"] == 3 * 2 * 3 * 2
    assert shape["axes"]["planes"] == 2


def test_models_are_an_axis_now():
    """The one §2.6 names first, and it was not reachable at all."""
    shape = bench.grid({"models": "gpt-4o-mini,claude-haiku-4-5"}, case_count=1)
    assert shape["axes"]["models"] == 2
    assert shape["runs"] == 2


def test_reps_are_bounded_rather_than_trusted():
    assert bench.grid({"reps": 99}, case_count=1)["axes"]["reps"] == 10


# ── and what it costs ───────────────────────────────────────────────────

def test_an_installation_that_measured_nothing_will_not_guess(conn):
    guess = bench.estimate(conn, {"planes": "api"}, case_count=3)
    assert guess["usd"] is None
    assert guess["runs"] == 3


def test_the_estimate_grows_with_the_grid(conn):
    _measured(conn)
    small = bench.estimate(conn, {"planes": "api"}, case_count=1)
    large = bench.estimate(conn, {"planes": "api", "reps": 4}, case_count=3)
    assert small["usd"] is not None
    assert large["usd"] > small["usd"]
    assert large["runs"] == 12


def test_a_grid_with_no_paid_plane_costs_nothing_and_says_so(conn):
    _measured(conn)
    guess = bench.estimate(conn, {"planes": "harness"}, case_count=5)
    assert guess["usd"] == 0.0
    assert "nothing to spend" in guess["note"]


def test_only_the_paid_half_of_a_mixed_grid_is_priced(conn):
    """A harness run's marginal cost really is zero — that is a measurement,
    not optimism."""
    _measured(conn)
    mixed = bench.estimate(conn, {"planes": "api,harness"}, case_count=4)
    paid_only = bench.estimate(conn, {"planes": "api"}, case_count=4)
    assert mixed["runs"] == 8
    assert mixed["usd"] == paid_only["usd"]


def test_each_llm_runs_on_the_plane_that_names_it():
    """`opus` is Claude Code's, `gpt-4o-mini` is the catalogue's: crossing
    them made two runs per pair that could only fail. A name nobody owns
    still sweeps every plane, and a plane left without one runs its default."""
    from app import bench

    owners = {"opus": {"harness"}, "gpt-4o-mini": {"api"}}
    assert bench.pairs(["harness", "api"], ["opus", "gpt-4o-mini", "my-gw/x"], owners) == [
        ("harness", "opus"), ("harness", "my-gw/x"),
        ("api", "gpt-4o-mini"), ("api", "my-gw/x"),
    ]
    assert bench.pairs(["harness", "api"], ["opus"], owners) == [("harness", "opus"), ("api", "")]
    assert bench.pairs(["api"], [], owners) == [("api", "")]
    shape = bench.grid({"planes": "harness,api", "llms": "opus,gpt-4o-mini", "reps": 2}, 3, owners)
    assert shape["runs"] == 3 * 2 * 2 and shape["paid_runs"] == 3 * 2
