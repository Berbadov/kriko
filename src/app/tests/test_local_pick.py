"""The Local model row is a pick like any agent, and it holds (#129).

"Local agent cannot be chosen in agents tab ... make sure that local agent
is usable." A pick of `local` must run on the local plane at every door, and
when its server is down the run fails with the reason; it never quietly
becomes whichever CLI is installed.
"""
from types import SimpleNamespace

import pytest

from app import localplane, prefs
from app.providers import harness
from app.web import state, tasks
from kriko.research.agent import AgentResearcher
from kriko.research.base import ResearchTask

READY = {"ready": True, "model": "m", "name": "srv", "url": "http://127.0.0.1:1",
         "reason": "", "models": ["m"]}
DOWN = {"ready": False, "model": "", "name": "", "url": "", "reason": "nothing listens",
        "models": []}


def _settings(tmp_path, pick=""):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        prefs.write(conn, {prefs.HARNESS: pick})
    finally:
        conn.close()
    return SimpleNamespace(app_state_path=path)


@pytest.fixture
def a_cli_is_installed(monkeypatch):
    monkeypatch.setattr(harness, "chosen", lambda *_a, **_k: SimpleNamespace(id="some-cli"))


def test_naming_local_runs_local_even_with_a_cli_installed(tmp_path, a_cli_is_installed):
    settings = _settings(tmp_path)
    assert tasks._use_local_ask(settings, {"harness": "local"})


def test_the_stored_local_pick_runs_local(tmp_path, a_cli_is_installed):
    settings = _settings(tmp_path, pick="local")
    assert tasks._use_local_ask(settings, {})
    # A run that names another agent is that run's own choice.
    assert not tasks._picked_local({"harness": "some-cli"}, settings.app_state_path)
    assert not tasks._picked_local({"backend": "api"}, settings.app_state_path)


@pytest.mark.parametrize("probe", [READY, DOWN])
def test_an_unnamed_run_with_local_picked_is_on_the_local_plane(tmp_path, monkeypatch, probe):
    monkeypatch.setattr(localplane, "resolve", lambda *_a, **_k: dict(probe))
    settings = _settings(tmp_path, pick="local")
    plane, why = tasks.default_plane(settings.app_state_path)
    assert plane == "local"
    if not probe["ready"]:
        assert "nothing listens" in why


def test_the_research_brief_carries_the_source_kinds():
    task = ResearchTask(subject_id="s", subject_label="S", subject_kind="product",
                        pack_id="p", guidance=tasks._source_kinds_line(["forums", "reviews"]))
    brief = AgentResearcher().brief(task)
    assert "Go to these kinds of source first: owner forums" in brief
