"""Asking the local model a question starts an installed Ollama that is closed."""

import pytest

from app import agentinstall, localplane
from app.web import tasks

OLLAMA = "http://127.0.0.1:11434"


class Log:
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)

    def check(self):
        pass


def _plan(*, up: bool, models=("gemma4:e2b",)):
    row = {"name": "Ollama", "url": OLLAMA, "up": up, "models": list(models) if up else []}
    return {"servers": [row], "ready": up, "reason": "" if up else "Nothing answers", "models": row["models"]}


def test_closed_ollama_at_its_own_address_is_asleep():
    assert localplane.ollama_asleep(_plan(up=False), "")
    assert localplane.ollama_asleep(_plan(up=False), OLLAMA + "/v1")


def test_another_server_or_a_running_ollama_is_not_asleep():
    assert not localplane.ollama_asleep(_plan(up=False), "http://127.0.0.1:1234")
    assert not localplane.ollama_asleep(_plan(up=True), "")
    busy = _plan(up=False)
    busy["servers"][0]["busy"] = True
    assert not localplane.ollama_asleep(busy, "")


def test_a_question_starts_the_closed_ollama_and_then_runs(monkeypatch):
    plans = iter([_plan(up=False), _plan(up=True)])
    monkeypatch.setattr(localplane, "resolve", lambda *a, **k: next(plans))
    woke = []
    monkeypatch.setattr(agentinstall, "wake_local", lambda **k: woke.append(True) or True)
    plan = tasks._local_plan({"app_state_path": None}, with_search=False, progress=Log())
    assert woke == [True]
    assert plan["ready"]


def test_when_ollama_cannot_be_started_the_run_says_why(monkeypatch):
    monkeypatch.setattr(localplane, "resolve", lambda *a, **k: _plan(up=False))
    monkeypatch.setattr(agentinstall, "wake_local", lambda **k: False)
    with pytest.raises(tasks.LocalNotReady, match="Nothing answers"):
        tasks._local_plan({"app_state_path": None}, with_search=False)


def test_wake_starts_it_once_and_waits_for_the_answer(monkeypatch):
    answers = iter([False, False, True])
    started = []
    monkeypatch.setattr(agentinstall, "_answers", lambda base: next(answers))
    monkeypatch.setattr(agentinstall, "_ollama_exe", lambda: "ollama")
    monkeypatch.setattr(agentinstall, "_start_ollama", lambda: started.append(True))
    monkeypatch.setattr(agentinstall.time, "sleep", lambda s: None)
    log = Log()
    assert agentinstall.wake_local(progress=log, seconds=5)
    assert started == [True]
    assert any("starting it" in line for line in log.lines)


def test_wake_does_nothing_when_ollama_is_not_installed(monkeypatch):
    monkeypatch.setattr(agentinstall, "_answers", lambda base: False)
    monkeypatch.setattr(agentinstall, "_ollama_exe", lambda: "")
    monkeypatch.setattr(agentinstall, "_start_ollama", lambda: pytest.fail("nothing to start"))
    assert not agentinstall.wake_local()
