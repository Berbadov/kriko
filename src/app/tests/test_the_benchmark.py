"""B111 — the same case, every plane, measured.

*"Some very specific cases and cost measurements to understand how different
agents perform."* This is the row B123 (which protocol to use) and B124 (can a
coding-agent CLI be driven as a function at all) both wait on: each of those is
a question about ratios, and a ratio is a measurement or it is a guess.

Two properties make it a benchmark rather than a script, and both are gates
here: the cases are *derived* from the installed store rather than enumerated
in Python — a fixed list of subjects would be the hardcoded-car-data bug in
benchmark clothing, and meaningless for any pack that is not `cars` — and a run
writes nothing to the knowledge, because a benchmark that grew the pack it
measured would make its second run incomparable with its first.
"""

import pytest
from fastapi.testclient import TestClient

from app import bench
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


@pytest.fixture
def store(settings):
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    for index in "abc":
        conn.execute(
            "INSERT INTO subjects (subject_id, pack_id, kind, label)"
            " VALUES (?, 'probe', 'product', ?)",
            (f"s{index}", f"Thing {index}"),
        )
    conn.commit()
    return conn


def test_silent_progress_never_writes_job_state(monkeypatch):
    from app.web.jobs import Cancelled

    def forbidden(*args, **kwargs):
        pytest.fail("sandbox progress wrote app job state")

    def stop():
        raise Cancelled()

    monkeypatch.setattr(state, "update_job", forbidden)
    monkeypatch.setattr(state, "save_partial", forbidden)
    progress = bench._Silent(stop)
    progress.log("line")
    progress.set(0.5, "halfway")
    progress.partial({"documents": 1})
    assert progress.job_id == ""
    assert progress.result == {"documents": 1}
    assert progress.lines == ["line"]
    assert progress.cancelled
    with pytest.raises(Cancelled):
        progress.check()


@pytest.mark.parametrize("phase", ["fetch", "extract"])
def test_research_cancellation_retains_actual_documents_and_findings(settings, store, monkeypatch, phase):
    from app.web import tasks
    from app.web.jobs import Cancelled
    from kriko.research import ApiResearcher, ResearchTask
    import json

    stopping = False

    def check():
        if stopping:
            raise Cancelled()

    def fetch(url):
        nonlocal stopping
        stopping = phase == "fetch"
        return "The specific component fails."

    def complete(prompt):
        nonlocal stopping
        stopping = True
        return json.dumps([{
            "title": "Component failure", "quote": "The specific component fails.",
            "body": "A specific failure explanation.",
        }])

    researcher = ApiResearcher(
        lambda *a: [{"url": "https://example.test/one"}], fetch, complete,
    )
    monkeypatch.setattr(tasks, "_researcher", lambda params: researcher)
    monkeypatch.setattr(tasks, "plan_task", lambda *a, **k: ResearchTask(
        subject_id="sa", subject_label="Thing a", subject_kind="product",
        pack_id="probe", queries=("query",),
    ))
    progress = bench._Silent(check)
    with pytest.raises(Cancelled):
        tasks.research(settings, {"subject_id": "sa", "backend": "api"}, progress)
    assert progress.result["retained_documents"][0]["text"] == "The specific component fails."
    if phase == "extract":
        assert progress.result["pending_findings"][0]["title"] == "Component failure"
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


def test_real_agent_case_exercises_complete_progress_interface(settings, store):
    row = bench.run_case(settings, bench.cases(store)[0], plane="agent")
    assert not row.get("error"), row
    assert row["documents"] == 0
    assert not settings.app_state_path.exists()


@pytest.mark.parametrize("kind", ["specific", "bulk"])
def test_case_forwards_cancellation_without_recording_failure(settings, store, monkeypatch, kind):
    from app.web import tasks
    from app.web.jobs import Cancelled

    stopping = False
    calls = []

    def check():
        if stopping:
            raise Cancelled()

    def research(measured, params, progress):
        nonlocal stopping
        calls.append(params["subject_id"])
        progress.partial({"documents": 1})
        stopping = True
        progress.check()

    monkeypatch.setattr(tasks, "research", research)
    case = {**bench.cases(store)[0], "kind": kind, "subject_ids": ["sa", "sb"]}
    with pytest.raises(Cancelled):
        bench.run_case(settings, case, plane="api", check_cancelled=check)
    assert calls == ["sa"]
    assert not settings.app_state_path.exists()


def test_bench_job_retains_finished_cases_when_next_case_stops(settings, store, monkeypatch):
    from app.web import tasks
    from app.web.jobs import Cancelled

    progress = bench._Silent()
    calls = []

    def run_case(settings, case, **kwargs):
        assert kwargs["check_cancelled"] == progress.check
        calls.append(case.get("id") or case["subject_id"])
        if len(calls) == 2:
            raise Cancelled()
        return {"subject_id": case.get("id") or case["subject_id"],
                "subject": case.get("product") or case["label"]}

    monkeypatch.setattr(bench, "run_case", run_case)
    with pytest.raises(Cancelled):
        tasks.bench(settings, {"planes": "api", "cases": 3}, progress)
    from app import benchcases

    assert calls == [benchcases.load()[0]["id"], benchcases.load()[1]["id"]]
    assert progress.result["measurements"] == 1
    assert len(progress.result["rows"]) == 1
    conn = state.connect(settings.app_state_path)
    try:
        assert len(state.bench_runs(conn)) == 1
        assert state.list_jobs(conn) == []
    finally:
        conn.close()


def test_the_cases_come_off_the_store_rather_than_out_of_python(store):
    """A hand-written list of subjects would name cars, go stale the week a
    pack changed, and mean nothing for a pack that is not `cars`."""
    found = bench.cases(store, limit=2)
    assert [case["subject_id"] for case in found] == ["sa", "sb"]
    assert all(case["pack_id"] == "probe" for case in found)


def test_the_cases_are_the_same_on_the_second_run(store):
    """A benchmark whose cases move is not a benchmark."""
    assert bench.cases(store) == bench.cases(store)


def test_a_subject_that_has_claims_is_measured_first(store):
    """A subject nothing has ever researched measures the researcher against an
    empty baseline, which is the weakest case available."""
    store.execute(
        "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
        " severity, author_confidence, created_at)"
        " VALUES ('c1', 'probe', 'sc', 'known_issue', 'engine', 'high', 0.6,"
        " datetime('now'))"
    )
    store.commit()
    assert bench.cases(store, limit=1)[0]["subject_id"] == "sc"


def test_a_case_writes_nothing_to_the_real_store(settings, store, monkeypatch):
    """The load-bearing one. A run goes through the ordinary research path,
    which *accepts claims* — into a copy that is deleted with the case."""
    from app.web import tasks

    def fake_research(measured_settings, params, progress):
        # Write into whatever store it was handed, as a real run would.
        conn = connect(measured_settings.store_path)
        conn.execute(
            "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
            " severity, author_confidence, created_at)"
            " VALUES ('bench', 'probe', 'sa', 'known_issue', 'engine', 'high',"
            " 0.6, datetime('now'))"
        )
        conn.commit()
        conn.close()
        assert measured_settings.store_path != settings.store_path
        return {
            "documents": 2,
            "accepted": [{"title": "kept", "claim_id": "bench"}],
            "rejected": [{"title": "no", "reason": "quote not in the document"}],
            "tokens_used": 1234,
            "spent_usd": 0.0,
            "llm": "claude-code",
        }

    monkeypatch.setattr(tasks, "research", fake_research)
    row = bench.run_case(settings, bench.cases(store)[0], plane="harness")
    assert row["accepted"] == 1 and row["refused"] == 1 and row["documents"] == 2
    assert row["tokens"] == 1234
    assert row["ms"] is not None
    # And the real store is untouched.
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0


def test_a_case_measures_the_readers_settings_rather_than_a_fresh_install(
    settings, store, monkeypatch
):
    """The other half of the sandbox, and the half that was missing.

    Isolating writes is right; starting the sandbox's `app.sqlite` *empty* was
    not, because that is where preferences live. A benchmark run then read no
    preference at all and measured the defaults — so choosing a harness and
    pressing Benchmark reported numbers from a harness the reader had not
    chosen, with nothing on screen to say so.
    """
    from app.web import tasks

    conn = state.connect(settings.app_state_path)
    state.put_settings(conn, {"harness": "codex", "harness_model_codex": "gpt-5-probe"})
    conn.close()

    seen = {}

    def fake_research(measured_settings, params, progress):
        inner = state.connect(measured_settings.app_state_path)
        seen.update(state.all_settings(inner))
        # Still a copy, not the reader's own file — the isolation this rides
        # on must not be what pays for the fix.
        assert measured_settings.app_state_path != settings.app_state_path
        state.put_settings(inner, {"harness": "scribbled-by-the-benchmark"})
        inner.close()
        return {"documents": 0, "accepted": [], "rejected": [], "tokens_used": 0}

    monkeypatch.setattr(tasks, "research", fake_research)
    bench.run_case(settings, bench.cases(store)[0], plane="harness")

    assert seen.get("harness") == "codex", (
        "the benchmark ran against an empty app.sqlite, so it measured the "
        "defaults rather than what the reader chose"
    )
    assert seen.get("harness_model_codex") == "gpt-5-probe"

    after = state.connect(settings.app_state_path)
    kept = state.all_settings(after)
    after.close()
    assert kept["harness"] == "codex", "a benchmark wrote back into the reader's settings"


def test_a_plane_that_cannot_run_is_a_measurement_not_a_crash(
    settings, store, monkeypatch
):
    """"The harness plane fails four cases in five" is the finding B124 needs,
    and it only exists if a failure is recorded rather than raised."""
    from app.web import tasks

    def explode(*args, **kwargs):
        raise RuntimeError("Claude Code exited 1: not logged in")

    monkeypatch.setattr(tasks, "research", explode)
    row = bench.run_case(settings, bench.cases(store)[0], plane="harness")
    assert "not logged in" in row["error"]
    assert row["ms"] is not None


def test_the_summary_reports_the_rate_rather_than_the_count(settings):
    """A plane that returns thirty findings and keeps two is worse than one
    that returns four and keeps three. Only the rate says so."""
    conn = state.connect(settings.app_state_path)
    state.record_bench(conn, {"plane": "harness", "model": "claude-code",
                              "accepted": 2, "refused": 28, "ms": 1000})
    state.record_bench(conn, {"plane": "api", "model": "gpt-x",
                              "accepted": 3, "refused": 1, "ms": 2000,
                              "tokens": 5000, "usd": 0.05})
    by_plane = {row["plane"]: row for row in state.bench_summary(conn)}
    assert by_plane["harness"]["acceptance"] == pytest.approx(0.067, abs=0.001)
    assert by_plane["api"]["acceptance"] == 0.75
    assert by_plane["api"]["tokens"] == 5000


def test_the_same_model_under_two_protocols_is_two_measurements(settings):
    """B123's whole premise: the ratio is keyed by how the model was *used*,
    not only by which model it was."""
    conn = state.connect(settings.app_state_path)
    for protocol, batch in (("wide", 12), ("narrow", 3)):
        state.record_bench(conn, {"plane": "api", "model": "qwen", "protocol": protocol,
                                  "batch_size": batch, "accepted": 1, "refused": 1})
    assert len(state.bench_summary(conn)) == 2


def test_the_agent_plane_is_never_benchmarked(monkeypatch):
    """Its `gather` returns nothing by design — the plane *is* a brief handed
    to a person — so measuring it would measure the brief writer and report
    zero of everything."""
    from app.providers import harness

    monkeypatch.setattr(harness, "available", lambda: True)
    assert "agent" not in bench.planes_available(None)


def test_the_api_serves_what_would_be_measured_next(settings, store):
    """A reader looking at an empty benchmark needs to know what pressing the
    button would run, and a second request to find out is a second thing to
    forget."""
    client = TestClient(create_app(settings))
    body = client.get("/api/bench").json()
    assert [case["subject_id"] for case in body["cases"]] == ["sa", "sb", "sc"]
    assert body["runs"] == [] and body["summary"] == []


def test_the_job_refuses_rather_than_measuring_nothing(settings, store, monkeypatch):
    """A benchmark with no plane available is a sentence, not an empty table."""
    from app.web import tasks

    monkeypatch.setattr(bench, "planes_available", lambda settings, **kwargs: [])
    with pytest.raises(ValueError) as raised:
        tasks.bench(settings, {}, bench._Silent())
    assert "no plane" in str(raised.value)


def test_the_job_measures_every_case_on_every_plane(settings, store, monkeypatch):
    from app.web import tasks

    monkeypatch.setattr(
        bench, "run_case",
        lambda settings, case, **kw: {
            "subject_id": case["id"], "subject": case["product"],
            "plane": kw["plane"], "model": kw["plane"], "accepted": 1, "refused": 0,
            "ms": 10, "documents": 1, "findings": 1, "batch_id": kw.get("batch_id", ""),
        },
    )
    result = tasks.bench(
        settings, {"planes": "harness,api", "cases": 2}, bench._Silent()
    )
    assert len(result["rows"]) == 4
    assert {row["plane"] for row in result["rows"]} == {"harness", "api"}
    conn = state.connect(settings.app_state_path)
    assert len(state.bench_runs(conn)) == 4
    # One press, one batch: a comparison is only a comparison if the rows in it
    # were measured against each other.
    assert len({row["batch_id"] for row in state.bench_runs(conn)}) == 1


def test_bench_is_a_command_as_well_as_a_button(settings, store, monkeypatch):
    """The output of this is an *argument* — a sentence somebody pastes."""
    from app import cli

    monkeypatch.setattr(
        bench, "run_case",
        lambda settings, case, **kw: {
            "subject": case["product"], "plane": kw["plane"], "model": "x",
            "accepted": 1, "refused": 2, "ms": 1200, "tokens": 900,
        },
    )
    monkeypatch.setattr(bench, "planes_available", lambda settings: ["harness"])
    code = cli.main(["--store", str(settings.store_path), "bench", "--cases", "1"])
    assert code == 0


# ── B124: can a coding-agent CLI be driven as a function at all? ─────────────
#
# The hypothesis is the reader's: "code agent harnesses do not like to be used
# as functions; otherwise we would fix it easily." It is testable rather than
# arguable — if it is true, the harness plane's failures will not be random,
# they will cluster in the classes of thing a CLI does *instead of answering*.
#
# The benchmark cannot settle it here: that needs a real CLI, a real
# subscription and a machine the reader owns. What is built here is the
# instrument, and an instrument that reported only "four of five failed" would
# not distinguish the two answers.


def test_a_failure_is_classified_by_what_the_cli_did_instead_of_answering():
    assert bench.failure_class("Claude Code exited 1: not logged in") == "auth"
    assert bench.failure_class("Claude Code did not finish within 600s") == "timeout"
    assert bench.failure_class("NoHarness: not on PATH (claude)") == "start"
    assert bench.failure_class("the harness answered without a findings list") == "shape"
    assert bench.failure_class("usage limit reached") == "limit"
    assert bench.failure_class("") == ""


def test_a_failure_nobody_predicted_is_other_rather_than_silence():
    """A class list that quietly dropped what it did not recognise would make
    the distribution look cleaner than the run was."""
    assert bench.failure_class("Segmentation fault") == "other"


def test_failing_the_same_way_every_time_is_reported_as_such():
    """The distinction B124 turns on: a plane that fails randomly is unlucky, a
    plane that fails the same way every time is being mis-used."""
    same = bench.verdict(
        [
            {"plane": "harness", "error": "not logged in"},
            {"plane": "harness", "error": "Claude Code exited 1: oauth"},
            {"plane": "harness", "error": "please run /login"},
        ]
    )["planes"][0]
    assert same["dominant_failure"] == "auth"

    scattered = bench.verdict(
        [
            {"plane": "harness", "error": "not logged in"},
            {"plane": "harness", "error": "did not finish within 600s"},
            {"plane": "harness", "error": "Segmentation fault"},
            {"plane": "harness", "error": "usage limit reached"},
        ]
    )["planes"][0]
    assert scattered["failed"] == 4
    assert scattered["dominant_failure"] == ""


def test_the_two_planes_are_compared_on_what_survives_the_gate():
    """Not on what they returned: a plane that returns thirty findings and
    keeps two is worse than one that returns four and keeps three."""
    planes = {
        one["plane"]: one
        for one in bench.verdict(
            [
                {"plane": "harness", "accepted": 2, "refused": 28},
                {"plane": "api", "accepted": 3, "refused": 1},
            ]
        )["planes"]
    }
    assert planes["harness"]["acceptance"] < planes["api"]["acceptance"]


def test_the_benchmark_payload_never_names_a_word_the_interface_may_not_hold():
    """The interface cannot spell this one, so the boundary spells it instead.

    `test_ui_contains_no_pack_vocabulary` bans the word outright in `ui/`,
    because it means an LLM on this screen and a car's model in every pack
    about vehicles, and a payload key cannot say which. A producer and its
    reader disagreeing about a string across a boundary is how an entire class
    of pack came to be built, installed and unreachable, so this asserts on the
    served payload rather than on either side's intentions.
    """
    from app.web.routers import bench as bench_router

    served = bench_router._served(
        {"model": "some-llm", "protocol": "standard", "runs": 3}
    )
    assert served == {"llm": "some-llm", "protocol": "standard", "runs": 3}
    assert "model" not in served


def test_only_explicitly_selected_values_are_swept():
    assert bench.split_axis({}, "models", "model", "llms", "llm") == []
    assert bench.split_axis({"models": ""}, "models", "model") == []
    assert bench.split_axis(
        {"models": "gpt-4o-mini, claude-haiku-4-5"}, "models", "model"
    ) == ["gpt-4o-mini", "claude-haiku-4-5"]
    assert bench.split_axis(
        {"models": "a, a, b "}, "models", "model"
    ) == ["a", "b"]
    assert bench.split_axis(
        {"llms": "a,b"}, "models", "model", "llms", "llm"
    ) == ["a", "b"]
    assert bench.split_axis(
        {"search": "exa"}, "searches", "search"
    ) == ["exa"]
    shape = bench.grid(
        {"planes": "api, api", "protocols": "standard, standard",
         "searches": "exa, tavily", "models": "a,b", "reps": 2},
        case_count=1,
    )
    assert shape["axes"] == {
        "cases": 1, "planes": 1, "protocols": 1,
        "searches": 2, "models": 2, "reps": 2,
    }
    assert shape["runs"] == 8


def test_estimate_refuses_unknown_axis_values(settings, store):
    from app.web import state as app_state

    conn = app_state.connect(settings.app_state_path)
    try:
        with pytest.raises(ValueError, match="unknown plane"):
            bench.estimate(conn, {"planes": "quantum"}, case_count=1)
        with pytest.raises(ValueError, match="unknown protocol"):
            bench.estimate(conn, {"protocols": "nope"}, case_count=1)
        with pytest.raises(ValueError, match="unknown search"):
            bench.estimate(conn, {"searches": "nope"}, case_count=1)
    finally:
        conn.close()


def test_estimate_endpoint_refuses_unknown_values(settings, store):
    client = TestClient(create_app(settings))
    refused = client.post("/api/bench/estimate", json={"protocols": "nope"})
    assert refused.status_code == 422
    refused = client.post("/api/bench/estimate", json={"planes": "quantum"})
    assert refused.status_code == 422
    refused = client.post("/api/bench/estimate", json={"searches": "nope"})
    assert refused.status_code == 422
    allowed = client.post("/api/bench/estimate", json={"planes": "harness"})
    assert allowed.status_code == 200
    assert allowed.json()["usd"] == 0.0


def test_start_endpoint_refuses_unknown_values(settings, store):
    client = TestClient(create_app(settings))
    refused = client.post("/api/bench", json={"searches": "nope"})
    assert refused.status_code == 422
