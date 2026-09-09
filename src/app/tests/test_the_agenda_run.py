"""The unattended run, and the way back out of one.

`POST /api/agenda/run` is the button someone presses and walks away from, so
every test here is about a way it could go wrong while nobody is watching:

* **It must not deadlock.** `app/web/jobs.py` has a single worker. A job that
  submits jobs and waits for them hangs with a queue that never drains and two
  rows spinning forever — which looks like slowness, not like a bug, and is the
  exact mistake that is obvious in a design document and invisible in a diff.
  So the handler calls the research path *inline*, and a test asserts it never
  reaches `submit`.
* **It must not silently do less than it said.** `unknown_subject` rows carry
  no `subject_id` on purpose (B82: they are products readers asked about that
  no pack claims — demand for catalog coverage, not a task an agent can act
  on). Dropping them quietly would make a run of ten rows do seven and look
  complete.
* **It must stop when told, and when out of money.**
* **It must be reversible.** An unattended multi-row run that could not be
  undone is a liability rather than a feature, which is why undo landed first
  and why it tolerates a run whose claims are partly gone already.
"""

import ast
import inspect
import textwrap
import time

import pytest
from fastapi.testclient import TestClient

from app import agenda
from app.web import state, tasks
from app.web.app import create_app
from app.web.jobs import Cancelled, Progress
from app.web.settings import Settings
from kriko.research import BudgetExceeded
from kriko.store.db import connect


def _executable(source: str) -> str:
    """The source with its comments and docstrings removed.

    `ast.unparse` drops comments for free; the docstring nodes have to be
    popped by hand. What is left is only what runs.
    """
    tree = ast.parse(textwrap.dedent(source))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(
                body[0].value.value, str
            ):
                body.pop(0)
    return ast.unparse(tree)


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


def _seed(tmp_path, subjects=("s1", "s2", "s3")):
    """A pack with subjects and no claims — every row an `empty_subject` gap."""
    conn = connect(tmp_path / "k.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    for subject_id in subjects:
        conn.execute(
            "INSERT INTO subjects (subject_id, pack_id, kind, label)"
            " VALUES (?, 'probe', 'product', ?)",
            (subject_id, f"Thing {subject_id}"),
        )
    conn.commit()
    conn.close()


class _Recorder:
    """A `Progress` that records instead of writing rows."""

    def __init__(self, cancel_after: int | None = None):
        self.job_id = "job-1"
        self.lines: list[str] = []
        self.checks = 0
        self._cancel_after = cancel_after

    def set(self, fraction, message=""):
        self.lines.append(message)

    def log(self, message):
        self.lines.append(message)

    def check(self):
        self.checks += 1
        if self._cancel_after is not None and self.checks > self._cancel_after:
            raise Cancelled("stopped by the reader")


# ── the deadlock ─────────────────────────────────────────────────────────


def test_the_agenda_run_never_submits_a_job(tmp_path, monkeypatch):
    """The single-worker deadlock, held by a gate rather than by a comment.

    A sub-job would sit queued behind the job that queued it, forever.
    """
    _seed(tmp_path)
    calls = []
    monkeypatch.setattr(
        tasks, "research", lambda settings, params, progress: calls.append(params) or {}
    )
    tasks.agenda_run(_settings(tmp_path), {"rows": 3}, _Recorder())
    assert len(calls) == 3

    # And in the source, so a later refactor cannot reintroduce it. Read as
    # code rather than as text: the docstring explains the deadlock at length,
    # and prose should neither satisfy a rule about behaviour nor break one.
    assert "submit" not in _executable(inspect.getsource(tasks.agenda_run)), (
        "agenda_run reached the job runner"
    )


def test_each_subject_is_researched_once_even_when_it_has_several_rows(
    tmp_path, monkeypatch
):
    """The agenda ranks claims as well as subjects, so one car can be two rows.

    Two rows and one research run: not de-duplicating would spend the budget
    twice running the same queries.
    """
    _seed(tmp_path, subjects=("s1",))
    monkeypatch.setattr(
        agenda,
        "compute",
        lambda *a, **k: {
            "rows": [
                {"kind": "empty_subject", "subject_id": "s1", "pack_id": "probe"},
                {"kind": "thin_claim", "subject_id": "s1", "pack_id": "probe"},
            ],
            "note": "",
        },
    )
    seen = []
    monkeypatch.setattr(
        tasks, "research", lambda s, params, p: seen.append(params["subject_id"]) or {}
    )
    result = tasks.agenda_run(_settings(tmp_path), {"rows": 5}, _Recorder())
    assert seen == ["s1"]
    assert result["subjects"] == 1


# ── the rows nobody can research ─────────────────────────────────────────


def test_a_row_with_no_subject_is_skipped_and_said_out_loud(tmp_path, monkeypatch):
    """`unknown_subject` is a message to the catalog, not a task for an agent.

    Counted and reported — *"3 rows need a subject before anyone can research
    them"* — rather than dropped, which would make a ten-row run do seven and
    report success.
    """
    _seed(tmp_path, subjects=("s1",))
    monkeypatch.setattr(
        agenda,
        "compute",
        lambda *a, **k: {
            "rows": [
                {"kind": "unknown_subject", "subject_id": "", "identity": "a thing"},
                {"kind": "unknown_subject", "subject_id": "", "identity": "another"},
                {"kind": "empty_subject", "subject_id": "s1", "pack_id": "probe"},
            ],
            "note": "",
        },
    )
    researched = []
    monkeypatch.setattr(
        tasks,
        "research",
        lambda s, params, p: researched.append(params["subject_id"]) or {},
    )
    progress = _Recorder()
    result = tasks.agenda_run(_settings(tmp_path), {"rows": 5}, progress)
    assert researched == ["s1"]
    assert result["needs_a_subject"] == 2
    assert any("need a subject" in line for line in progress.lines)


# ── stopping ─────────────────────────────────────────────────────────────


def test_a_cancel_mid_row_stops_the_whole_run(tmp_path, monkeypatch):
    """Re-raised, not swallowed: the job runner is what marks the row
    cancelled, and reporting a stopped run as a finished one is worse than
    stopping late."""
    _seed(tmp_path)
    monkeypatch.setattr(tasks, "research", lambda s, params, p: {})
    with pytest.raises(Cancelled):
        tasks.agenda_run(_settings(tmp_path), {"rows": 3}, _Recorder(cancel_after=1))


def test_the_budget_is_shared_across_rows_not_handed_to_each(tmp_path, monkeypatch):
    """Ten rows at $0.40 each would be a $4.00 run wearing a $0.40 label."""
    _seed(tmp_path, subjects=("s1", "s2", "s3", "s4"))
    given = []

    def fake_research(settings, params, progress):
        given.append(params["budget_usd"])
        return {"spent_usd": 0.10, "accepted": [], "rejected": []}

    monkeypatch.setattr(tasks, "research", fake_research)
    result = tasks.agenda_run(
        _settings(tmp_path), {"rows": 4, "backend": "api", "budget_usd": 0.25}, _Recorder()
    )
    assert given == [0.25, pytest.approx(0.15), pytest.approx(0.05)], given
    assert result["stopped"] == "budget"
    assert len(result["rows"]) == 3, "it researched a row with no money left"


def test_a_budget_stop_inside_a_row_ends_the_run(tmp_path, monkeypatch):
    """Caught to *stop*, never to carry on: the next statement breaks."""
    _seed(tmp_path)
    calls = []

    def fake_research(settings, params, progress):
        calls.append(params["subject_id"])
        raise BudgetExceeded("out of money")

    monkeypatch.setattr(tasks, "research", fake_research)
    result = tasks.agenda_run(
        _settings(tmp_path), {"rows": 3, "backend": "api"}, _Recorder()
    )
    assert len(calls) == 1
    assert result["stopped"] == "budget"


def test_one_subject_that_cannot_be_researched_does_not_end_the_run(
    tmp_path, monkeypatch
):
    """A missing template or a refused query is a row's problem, not the
    agenda's — the alternative is a ten-row run that the first bad subject
    reduces to nothing."""
    _seed(tmp_path)
    calls = []

    def fake_research(settings, params, progress):
        calls.append(params["subject_id"])
        if len(calls) == 1:
            raise KeyError("no templates")
        return {"accepted": [{"claim_id": "c1", "title": "t"}], "rejected": []}

    monkeypatch.setattr(tasks, "research", fake_research)
    result = tasks.agenda_run(_settings(tmp_path), {"rows": 3}, _Recorder())
    assert len(calls) == 3
    assert result["kept"] == 2
    assert any("error" in row for row in result["rows"])


def test_the_unattended_door_defaults_to_the_plane_that_costs_nothing():
    """Third time in this codebase, deliberately: the door pressed by somebody
    who is not watching is the last place a default should start spending."""
    from app.web.routers.research import AgendaRunRequest

    assert AgendaRunRequest().backend == "agent"
    assert AgendaRunRequest().budget_usd == 0.0


# ── undo ─────────────────────────────────────────────────────────────────


def _run_with_claims(tmp_path, claims):
    """A finished research run whose claims are really in the store."""
    _seed(tmp_path, subjects=("s1",))
    store = connect(tmp_path / "k.sqlite")
    for claim_id, title in claims:
        store.execute(
            "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
            " severity, created_at) VALUES (?, 'probe', 's1', 'known_issue',"
            " 'general', 'medium', '2026-09-09')",
            (claim_id,),
        )
        store.execute(
            "INSERT INTO claim_text (claim_id, pack_id, lang, title)"
            " VALUES (?, 'probe', 'en', ?)",
            (claim_id, title),
        )
        store.execute(
            "INSERT INTO evidence (evidence_id, pack_id, claim_id, source_id, quote)"
            " VALUES (?, 'probe', ?, 'src', 'a quote')",
            (f"e-{claim_id}", claim_id),
        )
    store.commit()
    store.close()

    app_state = state.connect(tmp_path / "app.sqlite")
    state.open_research_run(
        app_state, "run-1", job_id="j1", plane="api", model="a-model",
        search_provider="exa", budget_usd=0.2,
    )
    state.record_run_claims(
        app_state, "run-1", "probe", "s1",
        [{"claim_id": cid, "title": title} for cid, title in claims],
    )
    state.close_research_run(app_state, "run-1", "done", 0.11)
    app_state.close()


def test_undoing_a_run_takes_its_claims_and_their_evidence_out(tmp_path):
    """Orphaned evidence is invisible: it breaks nothing and shows up nowhere,
    which is exactly why the reversal has to be exhaustive."""
    _run_with_claims(tmp_path, [("c1", "One"), ("c2", "Two")])
    result = tasks.research_undo(_settings(tmp_path), {"run_id": "run-1"}, _Recorder())
    assert result["removed"] == 2
    assert result["absent"] == 0

    store = connect(tmp_path / "k.sqlite")
    for table in ("claims", "claim_text", "evidence"):
        left = store.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert left == 0, f"{table} still has rows"
    store.close()


def test_undoing_a_run_whose_claims_are_partly_gone_reports_rather_than_fails(
    tmp_path,
):
    """A reader may have deleted one by hand, or a later run may have
    superseded it. A 500 on any of that is an undo nobody trusts."""
    _run_with_claims(tmp_path, [("c1", "One"), ("c2", "Two"), ("c3", "Three")])
    store = connect(tmp_path / "k.sqlite")
    store.execute("DELETE FROM claims WHERE claim_id = 'c2'")
    store.commit()
    store.close()

    result = tasks.research_undo(_settings(tmp_path), {"run_id": "run-1"}, _Recorder())
    assert result["removed"] == 2
    assert result["absent"] == 1
    assert "already absent" in result["note"]


def test_undoing_a_run_twice_is_a_no_op_that_says_so(tmp_path):
    """`removed_at` is what makes the second press honest rather than silent."""
    _run_with_claims(tmp_path, [("c1", "One")])
    settings = _settings(tmp_path)
    tasks.research_undo(settings, {"run_id": "run-1"}, _Recorder())
    again = tasks.research_undo(settings, {"run_id": "run-1"}, _Recorder())
    assert again["removed"] == 0
    assert "already been taken out" in again["note"]


def test_a_run_with_nothing_left_is_not_offered_an_undo(tmp_path):
    """A button that would do nothing is worse than no button."""
    _run_with_claims(tmp_path, [("c1", "One")])
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/research-runs/run-1").json()["undoable"] is True
        tasks.research_undo(settings, {"run_id": "run-1"}, _Recorder())
        body = client.get("/api/research-runs/run-1").json()
        assert body["undoable"] is False
        assert body["claims"] == 0
        assert body["removed"] == 1


def test_the_provenance_row_names_the_model_and_what_it_spent(tmp_path):
    """"Researched by an LLM" is not a provenance record; a model name is one."""
    _run_with_claims(tmp_path, [("c1", "One")])
    with TestClient(create_app(_settings(tmp_path))) as client:
        run = client.get("/api/research-runs").json()["runs"][0]
    assert run["plane"] == "api"
    assert run["model"] == "a-model"
    assert run["search_provider"] == "exa"
    assert run["spent_usd"] == 0.11
    assert run["budget_usd"] == 0.2


def test_undoing_a_run_that_does_not_exist_is_a_bad_request_not_a_failed_job(tmp_path):
    """Queuing a job that will immediately fail reports a mistake as a crash."""
    with TestClient(create_app(_settings(tmp_path))) as client:
        assert client.delete("/api/research-runs/nope").status_code == 404


def test_a_real_agenda_run_ends_up_in_the_run_list(tmp_path):
    """End to end on the $0 plane, through the job runner, with no key set.

    The agent plane gathers nothing by design, so this keeps nothing — what it
    proves is that the loop, the emitters and the provenance rows all connect.
    """
    _seed(tmp_path, subjects=("s1", "s2"))
    with TestClient(create_app(_settings(tmp_path))) as client:
        job_id = client.post("/api/agenda/run", json={"rows": 2}).json()["job_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            row = client.get(f"/api/jobs/{job_id}").json()
            if row["done"]:
                break
            time.sleep(0.02)
        assert row["state"] == "succeeded", row
        assert row["result"]["subjects"] == 2
        runs = client.get("/api/research-runs").json()["runs"]
    assert len(runs) == 2
    assert all(run["plane"] == "agent" for run in runs)
    # Nobody counted on this plane, so the column stays NULL rather than
    # claiming a measured zero.
    assert all(run["spent_usd"] is None for run in runs)
