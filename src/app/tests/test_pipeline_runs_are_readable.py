"""The pipeline writes three tables and, until now, nothing could read them.

`web/pipeline.py`'s own docstring said so: "nothing in the app reads them back
yet, and the rows are written so that they could be". A year later the sweep
found the same thing. The tables are pruned to 200 runs, `mark_interrupted`
exists to keep a killed run's row honest at startup — and no route selected a
single row, so the pipeline's account of what it did was write-only.

Two properties matter beyond "it returns something": a stage that never opened
is *visible* as never having opened (rather than absent from a list, which reads
as "fine"), and the events come back in the order they happened.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import pipeline, state
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def app_state(tmp_path):
    connection = state.connect(tmp_path / "app.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path, app_state):
    return TestClient(create_app(Settings(store_path=tmp_path / "store.sqlite",
                                          app_state_path=tmp_path / "app.sqlite")))


def _run(app_state, run_id="run-1", subject="VW Golf"):
    emitter = pipeline.Emitter(app_state_path=None, kind="research")
    emitter.run_id = run_id
    connection = app_state
    connection.execute(
        "INSERT INTO pipeline_runs (run_id, kind, subject, pack_id, plane, state,"
        " sources, findings, accepted, refused, started_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, "research", subject, "org.test", "api", "done", 4, 9, 6, 3,
         "2026-10-18T10:00:00"),
    )
    connection.commit()
    return emitter


def test_a_run_is_listed_with_its_totals(app_state, client):
    _run(app_state)
    body = client.get("/api/pipeline-runs").json()
    assert body["total"] == 1
    assert body["stages"] == ["discovery", "extraction", "ingestion", "ledgering"]
    row = body["runs"][0]
    assert row["subject"] == "VW Golf"
    assert (row["accepted"], row["refused"]) == (6, 3)


def test_a_run_detail_shows_every_stage_in_order_even_unopened_ones(app_state, client):
    _run(app_state)
    app_state.execute(
        "INSERT INTO pipeline_stages (run_id, stage, seq, state, items, started_at)"
        " VALUES ('run-1','discovery',0,'done',4,'2026-10-18T10:00:00')")
    app_state.execute(
        "INSERT INTO pipeline_stages (run_id, stage, seq, state, items, started_at)"
        " VALUES ('run-1','extraction',1,'running',0,'2026-10-18T10:00:05')")
    app_state.commit()

    body = client.get("/api/pipeline-runs/run-1").json()
    stages = [(one["stage"], one["state"]) for one in body["stages"]]
    assert stages == [
        ("discovery", "done"),
        ("extraction", "running"),
        # Never opened. Listed, and named as never opened: a stage missing from
        # the list reads as "fine", which is the opposite of the truth.
        ("ingestion", "absent"),
        ("ledgering", "absent"),
    ]


def test_events_come_back_in_the_order_they_happened(app_state, client):
    _run(app_state)
    for index, level in enumerate(("info", "kept", "refused", "warn")):
        app_state.execute(
            "INSERT INTO pipeline_events (run_id, stage, at, level, message)"
            " VALUES ('run-1','extraction',?,?,?)",
            (f"2026-10-18T10:00:0{index}", level, f"event {index}"))
    app_state.commit()

    body = client.get("/api/pipeline-runs/run-1").json()
    assert [one["message"] for one in body["events"]] == [
        "event 0", "event 1", "event 2", "event 3"]


def test_an_unknown_run_is_a_404(client):
    answer = client.get("/api/pipeline-runs/nope")
    assert answer.status_code == 404
    assert "no pipeline run" in answer.json()["detail"]


def test_the_limit_is_bounded(client):
    assert client.get("/api/pipeline-runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/pipeline-runs", params={"limit": 9999}).status_code == 422


def test_the_newest_run_is_first(app_state, client):
    _run(app_state, run_id="old")
    _run(app_state, run_id="new")
    app_state.execute(
        "UPDATE pipeline_runs SET started_at = '2026-10-18T11:00:00' WHERE run_id = 'new'")
    app_state.commit()
    body = client.get("/api/pipeline-runs").json()
    assert [one["run_id"] for one in body["runs"]] == ["new", "old"]
