"""What the knowledge pipeline did, and whether it can be believed.

The reader's complaint was that "the terminal is not functioning". It was
functioning — it was reporting a job's *progress*, which cannot answer the
question actually being asked: did this run find nothing, or did it find
plenty and lose it all at the grounding check? Those look identical in a job
log and are completely different problems.

So these tests hold the properties that make the pipeline view worth trusting:

* a run that crashes is *readable* afterwards, with the failure on it
* a stage that correctly did nothing is `skipped`, not `done` with zero
* NULL tokens and zero tokens are different facts and stay different
* a run killed by a restart says `interrupted`, it does not say `running`
* telemetry that cannot be written never takes the research run down with it
* the emitter is in the interface layer and the engine emits nothing

The last one is the load-bearing one. An emitter reachable from `kriko/` would
make "add a category" mean "touch the engine", which is G6.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web import pipeline, state
from app.web.app import create_app
from app.web.settings import Settings

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def app_state(tmp_path):
    return tmp_path / "app.sqlite"


@pytest.fixture
def conn(app_state):
    connection = state.connect(app_state)
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


# ── the shape of a run ───────────────────────────────────────────────────


def test_a_run_records_its_stages_in_pipeline_order(app_state, conn):
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin(subject_id="s1", subject="A thing", pack_id="cars")
    for stage in pipeline.STAGES:
        emit.open_stage(stage)
    emit.finish()

    stages = pipeline.stages(conn, emit.run_id)
    assert [row["stage"] for row in stages] == list(pipeline.STAGES)
    assert [row["seq"] for row in stages] == [0, 1, 2, 3]


def test_every_stage_is_present_before_it_has_run(app_state, conn):
    """The view shows a shape, it does not grow one.

    Four boxes that fill in reads as a pipeline making progress. Four boxes
    that appear one at a time reads as a UI loading.
    """
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("discovery")

    states = {row["stage"]: row["state"] for row in pipeline.stages(conn, emit.run_id)}
    assert states == {
        "discovery": "running",
        "extraction": "waiting",
        "ingestion": "waiting",
        "ledgering": "waiting",
    }


def test_opening_the_next_stage_closes_the_one_before(app_state, conn):
    """A handler that fell through has, by definition, finished the stage it
    fell out of. A rule beats asking every call site to remember."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("discovery")
    emit.open_stage("extraction")

    states = {row["stage"]: row["state"] for row in pipeline.stages(conn, emit.run_id)}
    assert states["discovery"] == "done"
    assert states["extraction"] == "running"


def test_a_stage_that_did_nothing_on_purpose_is_skipped_not_done(app_state, conn):
    """The agent plane's `gather` returns nothing *by design* — it is the $0
    path. "Extraction: done, 0 findings" reads as a fault; `skipped` with a
    reason reads as the thing working."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.skip_stage("extraction", "the agent plane fetches nothing itself")

    row = next(
        r for r in pipeline.stages(conn, emit.run_id) if r["stage"] == "extraction"
    )
    assert row["state"] == "skipped"
    assert "agent plane" in row["detail"]


def test_a_stage_still_open_when_the_run_ends_failed_with_it(app_state, conn):
    """The interesting failures are exactly the ones that do not unwind
    tidily, so the run closes them rather than trusting the handler to."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("extraction")
    emit.finish("failed", "RuntimeError: the source went away")

    row = next(
        r for r in pipeline.stages(conn, emit.run_id) if r["stage"] == "extraction"
    )
    assert row["state"] == "failed"
    assert pipeline.get_run(conn, emit.run_id)["error"].startswith("RuntimeError")


# ── counts and events ────────────────────────────────────────────────────


def test_counts_accumulate_across_stages(app_state, conn):
    """Additive, so a stage never has to know what the ones before it found."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("discovery")
    emit.count(sources=3)
    emit.open_stage("extraction")
    emit.count(findings=2)
    emit.count(findings=5)
    emit.open_stage("ingestion")
    emit.count(accepted=4, refused=3)
    emit.finish()

    run = pipeline.get_run(conn, emit.run_id)
    assert (run["sources"], run["findings"]) == (3, 7)
    assert (run["accepted"], run["refused"]) == (4, 3)


def test_a_refusal_is_a_first_class_event_with_its_source(app_state, conn):
    """The refusals are the point of the ledger. A view that shows only what
    was kept cannot explain a run that kept nothing."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("ledgering")
    emit.event(
        "refused “DPF blocks”: no quote in the source",
        level="refused",
        source_url="https://example.test/thread/1",
        claim_id="",
    )
    events = pipeline.events(conn, emit.run_id)
    assert len(events) == 1
    assert events[0]["level"] == "refused"
    assert events[0]["source_url"] == "https://example.test/thread/1"
    assert events[0]["detail"] == {"claim_id": ""}


def test_events_are_cursored_by_id_not_by_time(app_state, conn):
    """Two events in the same second are ordinary. A time cursor would either
    repeat them or skip them depending on which way the comparison fell."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("discovery")
    for index in range(5):
        emit.event(f"source {index}")

    first = pipeline.events(conn, emit.run_id, limit=2)
    assert [e["message"] for e in first] == ["source 0", "source 1"]
    rest = pipeline.events(conn, emit.run_id, after=first[-1]["event_id"])
    assert [e["message"] for e in rest] == ["source 2", "source 3", "source 4"]


def test_the_event_log_is_bounded(app_state, conn, monkeypatch):
    """One run reading a pathological source must not be able to fill the
    reader's disk with its own telemetry."""
    monkeypatch.setattr(pipeline, "MAX_EVENTS_PER_RUN", 10)
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("discovery")
    for index in range(50):
        emit.event(f"event {index}")
    assert len(pipeline.events(conn, emit.run_id, limit=1000)) == 10


def test_an_unnamed_stage_is_not_silently_accepted(app_state):
    """A typo'd stage name would render as a box that never fills. Better to
    fail in the handler where the typo is."""
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    with pytest.raises(ValueError):
        emit.open_stage("discovry")


# ── honesty about tokens ─────────────────────────────────────────────────


def test_nobody_counting_tokens_is_not_the_same_as_zero_tokens(app_state, conn):
    """The agent plane's marginal cost really is zero and the API plane's
    really is measured. A run where nothing counted must not render as free —
    that is the `raised: true` mistake in another column."""
    unmeasured = pipeline.Emitter(app_state, kind="research")
    unmeasured.begin()
    unmeasured.finish()
    measured = pipeline.Emitter(app_state, kind="research")
    measured.begin()
    measured.describe(tokens=0)
    measured.finish()

    assert pipeline.get_run(conn, unmeasured.run_id)["tokens"] is None
    assert pipeline.get_run(conn, unmeasured.run_id)["tokens_counted"] is False
    assert pipeline.get_run(conn, measured.run_id)["tokens"] == 0
    assert pipeline.get_run(conn, measured.run_id)["tokens_counted"] is True


# ── surviving a restart ──────────────────────────────────────────────────


def test_a_run_running_at_startup_was_killed_not_is_running(app_state, conn):
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.open_stage("extraction")

    assert pipeline.mark_interrupted(conn) == 1
    run = pipeline.get_run(conn, emit.run_id)
    assert run["state"] == "interrupted"
    assert run["ended_at"]
    assert "stopped" in run["error"]
    stage = next(
        r for r in pipeline.stages(conn, emit.run_id) if r["stage"] == "extraction"
    )
    assert stage["state"] == "failed"


def test_startup_reconciles_the_pipeline_the_way_it_reconciles_jobs(tmp_path):
    """Not a unit test of `mark_interrupted` — a test that the app actually
    calls it. The function existing and never running is the failure mode."""
    app_state = tmp_path / "app.sqlite"
    emit = pipeline.Emitter(app_state, kind="research")
    emit.begin()
    emit.close()

    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=app_state,
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        body = client.get("/api/pipeline/runs").json()
    assert body["runs"][0]["state"] == "interrupted"


def test_old_runs_are_dropped_whole(app_state, conn, monkeypatch):
    """Events and stages go with the run. Half an event log is more
    misleading than none."""
    monkeypatch.setattr(pipeline, "MAX_RUNS", 3)
    ids = []
    for index in range(6):
        emit = pipeline.Emitter(app_state, kind="research")
        emit.begin()
        emit.open_stage("discovery")
        emit.event(f"run {index}")
        emit.finish()
        ids.append(emit.run_id)

    kept = {row["run_id"] for row in pipeline.runs(conn, limit=100)}
    assert len(kept) <= 4  # the cap, plus the one being inserted
    gone = next(run_id for run_id in ids if run_id not in kept)
    assert pipeline.events(conn, gone) == []
    assert not any(
        row["state"] != "waiting" for row in pipeline.stages(conn, gone)
    )


# ── the instrument does not break the experiment ─────────────────────────


def test_an_emitter_with_nowhere_to_write_still_works(tmp_path):
    """The CLI and MCP doors drive the same handler with no app.sqlite. A
    `None` emitter that raised would mean every call site grows an `if`, and
    one forgotten `if` is an AttributeError inside a research run."""
    emit = pipeline.Emitter(None, kind="research")
    emit.begin(subject_id="s1")
    emit.open_stage("discovery")
    emit.count(sources=2)
    emit.event("nothing is recorded, and that is fine")
    emit.finish()


def test_a_broken_database_never_fails_the_run_it_is_watching(tmp_path):
    """An instrument that destroys the experiment is worse than no
    instrument. Losing an event is cosmetic; failing a research run because
    its telemetry could not be written is not."""
    poisoned = tmp_path / "app.sqlite"
    poisoned.write_bytes(b"this is not a database")
    emit = pipeline.Emitter(poisoned, kind="research")
    emit.begin()
    emit.open_stage("discovery")
    emit.event("still no exception")
    emit.finish()


# ── the layering ─────────────────────────────────────────────────────────


def test_the_engine_emits_nothing_and_knows_nothing_about_this(app_state):
    """G6, in the one place it would be easiest to lose.

    A `Researcher` implementation that had to report progress to an interface
    would make adding a category mean touching the engine. The stage
    boundaries all live in the driver because the driver is what sequences
    them.
    """
    hits = []
    for path in (REPO / "src" / "kriko").rglob("*.py"):
        if "/tests/" in str(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "pipeline_runs" in text or "app.web" in text or "Emitter" in text:
            hits.append(path.relative_to(REPO))
    assert hits == []


def test_the_pipeline_tables_are_interface_state_not_engine_schema(app_state, conn):
    """Uninstalling a pack must not drop the record of what was run, and a
    run's telemetry must not move a pack's `content_digest`. Two SQLite files,
    on purpose."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"pipeline_runs", "pipeline_stages", "pipeline_events"} <= tables

    from kriko.store.db import SCHEMA_PATH

    assert "pipeline_runs" not in SCHEMA_PATH.read_text()


# ── the API ──────────────────────────────────────────────────────────────


def test_the_runs_endpoint_names_the_stages_so_the_ui_need_not(client):
    """The stage vocabulary is the server's. A second list in TypeScript is a
    second place to forget — the same reasoning that keeps identity keys out
    of `ui/src/`."""
    body = client.get("/api/pipeline/runs").json()
    assert [row["stage"] for row in body["stages"]] == list(pipeline.STAGES)
    assert body["runs"] == []


def test_one_run_comes_back_with_its_stages_totals_and_events(client, tmp_path):
    emit = pipeline.Emitter(tmp_path / "app.sqlite", kind="research")
    emit.begin(subject_id="s1", subject="A thing", pack_id="cars")
    emit.open_stage("discovery")
    emit.count(sources=2)
    emit.event("source: example.test", source_url="https://example.test/1")
    emit.finish()

    body = client.get(f"/api/pipeline/runs/{emit.run_id}").json()
    assert body["run"]["subject"] == "A thing"
    assert body["run"]["sources"] == 2
    assert len(body["stages"]) == len(pipeline.STAGES)
    assert body["events"][0]["source_url"] == "https://example.test/1"
    assert body["cursor"] == body["events"][-1]["event_id"]
    assert body["live"] is False


def test_asking_for_a_run_that_never_existed_says_so(client):
    assert client.get("/api/pipeline/runs/nope").status_code == 404


def test_the_frame_carries_the_cursor_so_the_client_cannot_disagree(client, tmp_path):
    emit = pipeline.Emitter(tmp_path / "app.sqlite", kind="research")
    emit.begin()
    emit.open_stage("discovery")
    for index in range(3):
        emit.event(f"event {index}")
    emit.finish()

    first = client.get(f"/api/pipeline/runs/{emit.run_id}").json()
    again = client.get(
        f"/api/pipeline/runs/{emit.run_id}", params={"after": first["cursor"]}
    ).json()
    assert again["events"] == []
    assert again["cursor"] == first["cursor"]


def test_the_stream_is_server_sent_events_and_ends_itself(client, tmp_path):
    """A stream held open against a run that will never change again is a
    connection leaked for the life of the process."""
    emit = pipeline.Emitter(tmp_path / "app.sqlite", kind="research")
    emit.begin(subject="A thing")
    emit.open_stage("ingestion")
    emit.event("kept “something”", level="kept")
    emit.finish()

    with client.stream("GET", "/api/pipeline/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    frames = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert frames
    assert frames[0]["run"]["subject"] == "A thing"
    assert frames[0]["events"][0]["level"] == "kept"


def test_the_stream_opens_on_whatever_is_running(client, tmp_path):
    """A view that opens empty while a run is in flight is the failure this
    whole subsystem exists to fix — so `latest` prefers a live run over a
    more recent finished one."""
    app_state = tmp_path / "app.sqlite"
    done = pipeline.Emitter(app_state, kind="research")
    done.begin(subject="finished")
    done.finish()
    live = pipeline.Emitter(app_state, kind="research")
    live.begin(subject="going")
    live.close()

    conn = state.connect(app_state)
    try:
        assert pipeline.latest(conn)["run_id"] == live.run_id
    finally:
        conn.close()


# ── the handler actually emits ────────────────────────────────────────────
#
# The tests above hold the spine's properties. These two hold the thing that
# is actually easy to get wrong: an emitter that exists, is correct, and is
# never called. A subsystem wired to nothing passes every unit test it has.


def _wait(client, job_id, seconds=10.0):
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = client.get(f"/api/jobs/{job_id}").json()
        if row["done"]:
            return row
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def test_a_real_research_run_writes_its_four_stages(client, tmp_path):
    """The agent plane end to end. Discovery ran; the three stages after it
    are `skipped` with reasons, because on the $0 path there is genuinely
    nothing to extract — and that must not read as three failures."""
    from kriko.store.db import connect

    conn = connect(tmp_path / "k.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Probe Thing')"
    )
    conn.commit()
    conn.close()

    # `backend` named rather than left to the default: an unnamed plane now
    # resolves to whichever one this machine can gather with, and this test is
    # about what the $0 plane records.
    job_id = client.post(
        "/api/research", json={"subject_id": "s1", "backend": "agent"}
    ).json()["job_id"]
    row = _wait(client, job_id)
    assert row["state"] == "succeeded", row

    run_id = row["result"]["run_id"]
    body = client.get(f"/api/pipeline/runs/{run_id}").json()
    assert body["run"]["state"] == "done"
    assert body["run"]["subject"] == "Probe Thing"
    assert body["run"]["pack_id"] == "probe"
    assert body["run"]["plane"] == "agent"
    # Nobody counted, so the column stays NULL rather than claiming free.
    assert body["run"]["tokens"] is None

    states = {row["stage"]: row["state"] for row in body["stages"]}
    assert states["discovery"] == "done"
    assert states["extraction"] == "skipped"
    assert states["ingestion"] == "skipped"
    assert states["ledgering"] == "skipped"

    # The plane and its cost basis are on the record. A bare subject renders
    # no queries — `rendered_queries()` needs identity to fill a template —
    # and that absence is itself the interesting fact, so the assertion is on
    # what a run always emits rather than on what this fixture happens to.
    assert any("agent plane" in event["message"] for event in body["events"])
    # And the run is linked back to the job it came from, so the two views
    # are two views of one thing rather than two records.
    assert body["run"]["job_id"] == job_id


def test_a_failed_research_run_is_readable_afterwards(client):
    """A crash in planning used to leave nothing at all — which is precisely
    the run somebody opens the pipeline view to understand."""
    job_id = client.post("/api/research", json={"subject_id": "nope"}).json()["job_id"]
    row = _wait(client, job_id)
    assert row["state"] == "failed"

    runs = client.get("/api/pipeline/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["state"] == "failed"
    assert runs[0]["subject_id"] == "nope"
    assert "KeyError" in runs[0]["error"]
    # The stage it died in, not just the fact that it died.
    stages = client.get(f"/api/pipeline/runs/{runs[0]['run_id']}").json()["stages"]
    assert next(s for s in stages if s["stage"] == "discovery")["state"] == "failed"
