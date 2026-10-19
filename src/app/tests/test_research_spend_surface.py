"""The three research surfaces the module docstring has promised since it existed.

`routers/research.py` opened with:

* `GET /api/research-runs` says what each run cost and what it added;
* `GET /api/usage` adds the sums up, which no per-run row can answer;
* `DELETE /api/research-runs/{id}` takes a run's claims back out.

Only `/research-planes` was ever defined here. `state.research_runs` was read by
the chat context builder and by nothing over HTTP, so a reader whose research
spends their own money could see one run's cost inside an answer and had no way
to list runs, total them, or reverse one. The undo was worse than missing: the
job handler existed, tested, and **nothing submitted it** — the route that would
have was the missing piece.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    for index, (spent, tokens) in enumerate(((1.5, 1200), (0.25, 300))):
        state.open_research_run(
            connection, run_id=f"run-{index}", job_id=f"job-{index}",
            plane="api", model="a-model", search_provider="exa",
            budget_usd=2.0,
        )
        connection.execute(
            "UPDATE research_runs SET spent_usd = ?, tokens_used = ?, outcome = 'done',"
            " ended_at = '2026-10-18T00:00:0' || ? WHERE run_id = ?",
            (spent, tokens, index, f"run-{index}"),
        )
        connection.execute(
            "INSERT INTO research_run_claims (run_id, pack_id, claim_id, subject_id,"
            " title, removed_at) VALUES (?,?,?,?,?,NULL)",
            (f"run-{index}", "tools", f"c-{index}", "s-1", f"Claim {index}"),
        )
    connection.commit()
    connection.close()
    application = create_app(Settings(store_path=tmp_path / "store.sqlite",
                                      app_state_path=tmp_path / "app.sqlite"))
    return TestClient(application)


def test_runs_are_listed_newest_first_with_their_cost(client):
    body = client.get("/api/research-runs").json()
    assert [run["run_id"] for run in body["runs"]] == ["run-1", "run-0"]
    assert body["runs"][0]["spent_usd"] == 0.25
    assert body["runs"][0]["claims"] == 1
    assert body["total"] == 2


def test_the_limit_is_bounded(client):
    assert client.get("/api/research-runs", params={"limit": 1}).json()["total"] == 1
    assert client.get("/api/research-runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/research-runs", params={"limit": 10_000}).status_code == 422


def test_usage_adds_up_what_no_single_run_can(client):
    body = client.get("/api/usage").json()
    assert body["runs"] == 2
    assert body["claims"] == 2
    assert body["spent_usd"] == 1.75
    assert body["tokens_used"] == 1500
    assert body["runs_counted_in_usd"] == 2
    assert set(body["metered"]) == {"spent_usd", "tokens_used"}


def test_an_uncounted_column_is_not_zero(client, tmp_path):
    """A plane that cannot count and a plane that spent nothing differ."""
    connection = state.connect(tmp_path / "app2.sqlite")
    state.open_research_run(connection, run_id="free", job_id="j", plane="harness",
                            model="", search_provider="", budget_usd=0.0)
    connection.commit()
    connection.close()
    client2 = TestClient(create_app(Settings(store_path=tmp_path / "s2.sqlite",
                                             app_state_path=tmp_path / "app2.sqlite")))
    body = client2.get("/api/usage").json()
    assert body["runs"] == 1
    assert body["spent_usd"] is None       # not 0.0
    assert body["runs_counted_in_usd"] == 0


def test_undo_starts_the_job_the_handler_already_had(client):
    started = client.delete("/api/research-runs/run-0")
    assert started.status_code == 202
    body = started.json()
    assert body["run_id"] == "run-0"
    assert body["job_id"]


def test_undo_of_a_run_that_is_not_there_is_a_404(client):
    answer = client.delete("/api/research-runs/nope")
    assert answer.status_code == 404
    assert "no research run" in answer.json()["detail"]
