"""B97 — every plane reports what it used, and null means "cannot count".

The reader's complaint was one line: "I see no token info, no usage info etc."
It was accurate about three different things.

* The `research_runs` row had a dollar column and no token column, so the one
  plane that *does* know its tokens — the harness, which reads the CLI's own
  `usage` envelope — had nowhere to put them.
* The paid plane counted dollars per call and never counted tokens at all,
  because `complete(prompt) -> str` throws away the part of the reply the
  count lives in.
* Nothing anywhere summed anything. A per-run row cannot answer "what has
  this cost me", and the analyses log — the record of everything the reader
  ever looked up — had its *path* on the About screen and no reader of its
  contents.

The gate is the distinction that makes all of it trustworthy: **a plane that
cannot count writes NULL, never 0.** "Cost nothing" and "nobody measured" are
different answers, and a screen that renders an unmeasured run as $0.00 is
teaching the reader a number they will repeat. Every assertion below is
either "the plane that can count did" or "the plane that cannot did not
pretend to".
"""

import pytest
from fastapi.testclient import TestClient

from app.providers import llm
from app.web import state, tasks
from app.web.app import create_app
from app.web.settings import Settings
from kriko.research.api import ApiResearcher


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


class _Plane:
    """A researcher that reports exactly what it was told to report."""

    name = "probe"
    cost_basis = "per_token"

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


def _closed(tmp_path, researcher, outcome="done"):
    """One provenance row, opened and closed around a plane."""
    provenance = tasks._Provenance(_settings(tmp_path), "run-1", "j1", {})
    provenance.open(researcher)
    provenance.close(outcome)
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        return state.get_research_run(conn, "run-1")
    finally:
        conn.close()


# ── the column, and what an empty one means ──────────────────────────────


def test_a_plane_that_counts_tokens_gets_them_written_down(tmp_path):
    """The harness plane's shape: tokens and a cost, both reported."""
    row = _closed(tmp_path, _Plane(tokens_used=4200, spent=0.0))
    assert row["tokens_used"] == 4200
    assert row["spent_usd"] == 0.0


def test_a_plane_that_cannot_count_leaves_the_columns_null(tmp_path):
    """The agent plane's shape. NULL, not 0 — the whole point of B97.

    `AgentResearcher` has neither field, and the row must say so rather than
    claim a measured zero. A reader summing a column of invented zeros gets a
    total that is wrong in the direction that flatters us.
    """
    row = _closed(tmp_path, _Plane())
    for column in state.METERED:
        assert row[column] is None, f"{column} claimed a measurement nobody made"


@pytest.mark.parametrize("value", [None, "1200", True, object()])
def test_a_plane_that_reports_nonsense_counts_as_not_counting(tmp_path, value):
    """A string, a bool or nothing is not a measurement.

    `True` is in this list because `isinstance(True, int)` — a plane that
    reported a flag where a count belonged would otherwise be recorded as
    having used exactly one token.
    """
    row = _closed(tmp_path, _Plane(tokens_used=value))
    assert row["tokens_used"] is None


def test_the_usage_is_recorded_even_when_the_run_stopped_at_its_budget(tmp_path):
    """The one run whose cost is unrecoverable if it is not written on the way
    out. Same reason `spent` is read on every path — see `_Provenance.close`."""
    row = _closed(tmp_path, _Plane(tokens_used=99, spent=0.2), outcome="budget")
    assert row["outcome"] == "budget"
    assert (row["tokens_used"], row["spent_usd"]) == (99, 0.2)


def test_closing_a_run_twice_cannot_erase_what_was_counted(tmp_path):
    """`COALESCE` on each column, so a caller that knows one currency and not
    the other does not blank the one already written."""
    conn = state.connect(tmp_path / "app.sqlite")
    state.open_research_run(conn, "r", plane="api")
    state.close_research_run(conn, "r", "done", 0.05, 700)
    state.close_research_run(conn, "r", "done")
    row = state.get_research_run(conn, "r")
    conn.close()
    assert (row["spent_usd"], row["tokens_used"]) == (0.05, 700)


# ── the paid plane learns to count ───────────────────────────────────────


def test_the_completion_socket_counts_tokens_and_the_engine_reads_them():
    """The count can only come from the adapter that saw the envelope.

    `kriko/research/api.py` takes `complete(prompt) -> str` and must keep
    taking it — the engine owns no socket. So the total lives on the callable
    and the researcher reads it duck-typed, which is the same hook the model
    name and the search provider already travel on.
    """

    def complete(prompt):
        complete.tokens_used = (complete.tokens_used or 0) + 150
        return "[]"

    complete.tokens_used = None
    researcher = ApiResearcher(lambda q, n: [], lambda u: "", complete)
    assert researcher.tokens_used is None, "nothing has been asked yet"
    complete("first")
    complete("second")
    assert researcher.tokens_used == 300


def test_a_completer_that_never_reports_usage_is_not_counted_as_free():
    """A provider with no `usage` block leaves the total None, and the row
    then says "nobody counted" rather than "this cost nothing"."""
    researcher = ApiResearcher(lambda q, n: [], lambda u: "", lambda prompt: "[]")
    assert researcher.tokens_used is None


def test_the_llm_adapter_counts_what_the_provider_reported(monkeypatch):
    """Off the wire, including for a reply nothing could be parsed out of."""
    replies = [
        {"choices": [{"message": {"content": "[]"}}], "usage": {"total_tokens": 11}},
        {"error": "nope", "usage": {"total_tokens": 7}},
    ]
    monkeypatch.setattr(llm, "post_json", lambda *a, **k: replies.pop(0))
    complete = llm.completer(api_key="k", model="m")
    assert complete.tokens_used is None
    complete("one")
    assert complete.tokens_used == 11
    complete("two")
    assert complete.tokens_used == 18, "an unusable reply still cost tokens"


# ── the sum, which no per-run row can answer ─────────────────────────────


def _metered(conn, run_id, plane, spent, tokens, claims=0):
    state.open_research_run(conn, run_id, plane=plane, budget_usd=1.0)
    state.record_run_claims(
        conn, run_id, "probe", "s1",
        [{"claim_id": f"{run_id}-{n}"} for n in range(claims)],
    )
    state.close_research_run(conn, run_id, "done", spent, tokens)


def test_the_totals_say_how_many_of_the_runs_behind_them_were_counted(tmp_path):
    """A total with no denominator cannot be read. $0.08 over four runs means
    one thing if all four were metered and another if one was."""
    conn = state.connect(tmp_path / "app.sqlite")
    _metered(conn, "a", "api", 0.05, 500, claims=2)
    _metered(conn, "b", "api", 0.03, 300, claims=2)
    _metered(conn, "c", "agent", None, None)
    _metered(conn, "d", "harness", None, 900)
    totals = state.usage_totals(conn)
    conn.close()

    assert totals["runs"] == 4
    assert totals["metered_runs"] == 2
    assert totals["counted_runs"] == 3
    assert totals["spent_usd"] == pytest.approx(0.08)
    assert totals["tokens_used"] == 1700
    assert totals["claims"] == 4
    assert totals["cost_per_claim"] == pytest.approx(0.02)


def test_an_installation_that_never_metered_anything_reports_no_cost_per_claim(
    tmp_path,
):
    """Not $0.00. That is the number a reader would quote, and it is a lie
    with a decimal point on it."""
    conn = state.connect(tmp_path / "app.sqlite")
    _metered(conn, "a", "agent", None, None, claims=3)
    totals = state.usage_totals(conn)
    conn.close()
    assert totals["claims"] == 3
    assert totals["spent_usd"] is None
    assert totals["cost_per_claim"] is None


def test_a_run_whose_claims_were_undone_does_not_make_the_rest_look_cheaper(
    tmp_path,
):
    """`claims` counts what the runs still own. An undone run's cost is sunk,
    and quietly dropping it from the numerator would reward the undo."""
    conn = state.connect(tmp_path / "app.sqlite")
    _metered(conn, "a", "api", 0.10, 100, claims=2)
    conn.execute("UPDATE research_run_claims SET removed_at = '2026-09-10'")
    conn.commit()
    totals = state.usage_totals(conn)
    conn.close()
    assert totals["claims"] == 0
    assert totals["spent_usd"] == pytest.approx(0.10)
    assert totals["cost_per_claim"] is None, "a zero denominator is not a price"


def test_the_totals_are_broken_down_by_plane(tmp_path):
    """Which plane spent it, because that is the only actionable half: a
    reader who dislikes the number changes planes."""
    conn = state.connect(tmp_path / "app.sqlite")
    _metered(conn, "a", "api", 0.05, 500)
    _metered(conn, "b", "harness", None, 900)
    _metered(conn, "c", "harness", None, 100)
    planes = {row["plane"]: row for row in state.usage_totals(conn)["planes"]}
    conn.close()
    assert planes["harness"]["runs"] == 2
    assert planes["harness"]["tokens_used"] == 1000
    assert planes["harness"]["spent_usd"] is None
    assert planes["api"]["metered_runs"] == 1


# ── the analyses log finally has a reader ────────────────────────────────


def test_the_analyses_log_is_summarised_rather_than_only_located(tmp_path):
    """`About` shows the path. Nothing has ever read the file.

    `answered_nothing` is the number that earns this: a lookup that resolved
    and returned no claims is a coverage gap the reader personally hit.
    """
    from app.web import observability

    path = tmp_path / "a.jsonl"
    path.write_text(
        '{"subjects": ["s1"], "claim_titles": ["one", "two"], "adapter": "site"}\n'
        '{"subjects": ["s1"], "claim_titles": [], "adapter": "site"}\n'
        "not json at all\n"
        '{"subjects": ["s2"], "claim_titles": [], "adapter": ""}\n',
        encoding="utf-8",
    )
    summary = observability.summarise(path)
    assert summary["analyses"] == 3
    assert summary["malformed"] == 1
    assert summary["claims_shown"] == 2
    assert summary["answered_nothing"] == 2
    assert summary["subjects"] == 2
    assert summary["adapters"] == ["site"]


def test_a_log_that_does_not_exist_summarises_to_zero_rather_than_raising(tmp_path):
    """A fresh installation has no log, and asking about usage must not fail."""
    from app.web import observability

    assert observability.summarise(tmp_path / "nope.jsonl")["analyses"] == 0


# ── the route the screen reads ───────────────────────────────────────────


def test_the_usage_endpoint_reports_both_halves(tmp_path):
    """What was spent writing claims in, and what was asked reading them out.
    Neither half answers "what has this cost me" alone."""
    conn = state.connect(tmp_path / "app.sqlite")
    _metered(conn, "a", "api", 0.04, 400, claims=1)
    conn.close()
    (tmp_path / "a.jsonl").write_text(
        '{"subjects": ["s1"], "claim_titles": ["one"]}\n', encoding="utf-8"
    )
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.get("/api/usage").json()
    assert body["research"]["tokens_used"] == 400
    assert body["research"]["cost_per_claim"] == pytest.approx(0.04)
    assert body["analyses"]["analyses"] == 1


def test_usage_on_a_fresh_installation_is_zeroes_and_nulls_not_an_error(tmp_path):
    """The first screen a new reader sees. It must render, and it must not
    invent a spend of $0.00 out of an installation that has never run."""
    with TestClient(create_app(_settings(tmp_path))) as client:
        body = client.get("/api/usage").json()
    assert body["research"]["runs"] == 0
    assert body["research"]["spent_usd"] is None
    assert body["analyses"]["analyses"] == 0


def test_every_metered_column_reaches_the_wire(tmp_path):
    """The parity that keeps this honest as planes learn to count.

    `state.METERED` is the schema's own list. A third currency added to the
    column set but not to the run payload would be a measurement taken and
    never shown, which is the state B97 exists to end.
    """
    conn = state.connect(tmp_path / "app.sqlite")
    _metered(conn, "a", "api", 0.04, 400)
    conn.close()
    with TestClient(create_app(_settings(tmp_path))) as client:
        run = client.get("/api/research-runs").json()["runs"][0]
        totals = client.get("/api/usage").json()["research"]
    for column in state.METERED:
        assert column in run, f"{column} is recorded and never reported"
        assert column in totals, f"{column} is reported per run and never summed"
