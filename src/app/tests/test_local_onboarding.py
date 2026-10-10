"""Setup selects a usable model, and starting an installed app never installs it."""
from types import SimpleNamespace
from io import BytesIO
import json
import urllib.error

import pytest

from app import agentinstall, prefs
from app.web import state


class Progress:
    def check(self):
        pass

    def set(self, *args):
        pass

    def log(self, *args):
        pass


def test_setup_selects_the_downloaded_starter_in_the_readers_settings(tmp_path, monkeypatch):
    settings = SimpleNamespace(app_state_path=tmp_path / "app.sqlite")
    monkeypatch.setattr(agentinstall.os, "name", "nt")
    monkeypatch.setattr(agentinstall, "_set_up_local", lambda *args: {
        "id": "local", "installed": True, "model": agentinstall.STARTER_MODEL})
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda path: agentinstall.OLLAMA_URL)
    agentinstall.install(settings, {"agent_id": "local"}, Progress())
    conn = state.connect(settings.app_state_path)
    try:
        mine = prefs.read(conn)
        assert mine[prefs.LOCAL_URL] == agentinstall.OLLAMA_URL
        assert mine[prefs.LOCAL_MODEL] == agentinstall.STARTER_MODEL
    finally:
        conn.close()


def test_starting_an_installed_ollama_never_installs_or_pulls_a_model(monkeypatch):
    started = []
    monkeypatch.setattr(agentinstall, "_answers", lambda base: False)
    monkeypatch.setattr(agentinstall, "_ollama_exe", lambda: "installed/ollama.exe")
    monkeypatch.setattr(agentinstall, "_start_ollama", lambda: started.append(True))
    monkeypatch.setattr(agentinstall, "_wait_for_ollama", lambda *args: True)
    monkeypatch.setattr(agentinstall, "_run", lambda *args: pytest.fail("start must not install"))
    monkeypatch.setattr(agentinstall.modelpull, "pull", lambda *args: pytest.fail("start must not download"))
    assert agentinstall.start_local(Progress())["ready"]
    assert started == [True]


def test_a_missing_app_has_an_actionable_setup_message(monkeypatch):
    monkeypatch.setattr(agentinstall, "_answers", lambda base: False)
    monkeypatch.setattr(agentinstall, "_ollama_exe", lambda: "")
    with pytest.raises(RuntimeError, match="Download Ollama"):
        agentinstall.start_local(Progress())


def test_setup_refuses_ready_when_the_installed_model_cannot_run(monkeypatch, tmp_path):
    monkeypatch.setattr(agentinstall, "_answers", lambda base: True)
    monkeypatch.setattr(agentinstall.modelpull, "ollama_base", lambda *a: agentinstall.OLLAMA_URL)
    monkeypatch.setattr(agentinstall.modelpull, "installed", lambda *a: [{"name": agentinstall.STARTER_MODEL}])
    monkeypatch.setattr(agentinstall.modelpull, "pull", lambda *a: pytest.fail("model already downloaded"))

    def failed(request, **kwargs):
        assert request.full_url.endswith("/api/generate")
        raise urllib.error.HTTPError(request.full_url, 500, "Missing runner", {}, None)

    monkeypatch.setattr(agentinstall.urllib.request, "urlopen", failed)
    path = tmp_path / "app.sqlite"
    with pytest.raises(RuntimeError, match="update or repair"):
        agentinstall.install(SimpleNamespace(app_state_path=path), {"agent_id": "local"}, Progress())
    conn = state.connect(path)
    try:
        assert not prefs.read(conn).get(prefs.LOCAL_MODEL)
    finally:
        conn.close()


@pytest.mark.parametrize("result", [{"done": True}, {"done": True, "eval_count": 0},
                                    {"done": True, "eval_count": 1, "error": "bad"}])
def test_a_version_or_incomplete_generate_response_does_not_prove_readiness(monkeypatch, result):
    monkeypatch.setattr(agentinstall.urllib.request, "urlopen", lambda *a, **kw:
                        BytesIO(json.dumps(result).encode()))
    with pytest.raises(RuntimeError, match="could not answer"):
        agentinstall._verify_local(agentinstall.OLLAMA_URL, agentinstall.STARTER_MODEL, Progress())


def test_setup_probes_the_actual_model_with_a_bounded_generation(monkeypatch):
    seen = []

    def answered(request, **kwargs):
        seen.append(json.loads(request.data))
        return BytesIO(b'{"done": true, "eval_count": 1, "response": "OK"}')

    monkeypatch.setattr(agentinstall.urllib.request, "urlopen", answered)
    agentinstall._verify_local(agentinstall.OLLAMA_URL, agentinstall.STARTER_MODEL, Progress())
    assert seen[0]["model"] == agentinstall.STARTER_MODEL
    assert seen[0]["options"]["num_predict"] == 1
