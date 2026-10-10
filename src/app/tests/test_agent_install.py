"""One click installs an agent the way its vendor says, and says if Kriko can now run it."""

import pytest
from fastapi.testclient import TestClient

from app import agentinstall
from app.providers import harness
from app.web.app import create_app
from app.web.settings import Settings


class _Progress:
    def __init__(self):
        self.lines, self.steps = [], []

    def log(self, line):
        self.lines.append(line)

    def set(self, value, message=""):
        self.steps.append((value, message))

    def check(self):
        pass


@pytest.fixture(autouse=True)
def _windows(monkeypatch):
    monkeypatch.setattr(agentinstall.os, "name", "nt")


def test_the_shipped_agents_have_a_windows_install_that_is_not_a_bash_pipe():
    for ident in ("claude-code", "antigravity-cli", "codex", "mistral-vibe"):
        script = agentinstall.command_for(ident)
        assert script and "| bash" not in script and "curl " not in script, ident
        assert agentinstall.can_install(ident)


def test_the_local_agent_installs_ollama_and_an_unknown_agent_has_no_install():
    assert "Ollama.Ollama" in agentinstall.command_for("local")
    assert not agentinstall.can_install("no-such-agent")


def test_the_current_registered_install_wins_over_an_obsolete_path(monkeypatch):
    monkeypatch.setattr(agentinstall, "_registered_ollama_exe", lambda: "D:/local/Ollama/ollama.exe")
    monkeypatch.setattr(agentinstall.shutil, "which", lambda *a, **k: "C:/old/Ollama/ollama.exe")
    assert agentinstall._ollama_exe() == "D:/local/Ollama/ollama.exe"


def test_a_cli_install_runs_its_script_then_looks_for_the_cli(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(agentinstall, "_run", lambda script, progress: ran.append(script))
    monkeypatch.setattr(harness, "locate", lambda one: str(tmp_path / "claude.exe"))
    got = agentinstall.install(None, {"agent_id": "claude-code"}, _Progress())
    assert ran == [agentinstall.command_for("claude-code")]
    assert got["installed"] and got["path"].endswith("claude.exe")


def test_an_install_that_leaves_the_cli_unfindable_says_so(monkeypatch):
    monkeypatch.setattr(agentinstall, "_run", lambda script, progress: None)
    monkeypatch.setattr(harness, "locate", lambda one: "")
    with pytest.raises(RuntimeError, match="cannot find it"):
        agentinstall.install(None, {"agent_id": "codex"}, _Progress())


def test_the_local_setup_skips_what_is_already_there(monkeypatch):
    monkeypatch.setattr(agentinstall, "_verify_local", lambda *a: None)
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path=None: "")
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda base: [{"name": agentinstall.STARTER_MODEL}])
    monkeypatch.setattr(agentinstall, "_run", lambda *a: pytest.fail("Ollama is already running"))
    monkeypatch.setattr(agentinstall.modelpull, "pull", lambda *a: pytest.fail("the model is already there"))
    got = agentinstall.install(None, {"agent_id": "local"}, _Progress())
    assert got == {"id": "local", "installed": True, "model": agentinstall.STARTER_MODEL}


def test_the_local_setup_downloads_the_starter_model_when_ollama_has_none(monkeypatch):
    monkeypatch.setattr(agentinstall, "_verify_local", lambda *a: None)
    pulled = []
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path=None: "http://127.0.0.1:11434")
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda base: [])
    monkeypatch.setattr(agentinstall.modelpull, "pull", lambda base, model, progress: pulled.append(model) or {})
    agentinstall.install(None, {"agent_id": "local"}, _Progress())
    assert pulled == [agentinstall.STARTER_MODEL]


def test_the_route_refuses_what_it_cannot_install(tmp_path):
    client = TestClient(create_app(Settings(
        store_path=tmp_path / "k.sqlite", packs_dir=tmp_path / "packs", analysis_log_path=tmp_path / "a.jsonl",
        dist_dir=tmp_path / "dist", app_state_path=tmp_path / "app.sqlite")))
    assert client.post("/api/agents/no-such-agent/install").status_code == 404
