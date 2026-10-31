"""A host-read turn starts its agent while Kriko is reading the pages.

The host-read path spends one to twenty seconds searching and reading before
the agent is asked anything; a resident CLI (Claude Code, Mistral Vibe) needs
some of those seconds to start and open a session. Warming it in the background
turns the cold start into time already being spent. The warm-up must be
once-per-turn, only for protocols that have a resident worker, and harmless
when it fails.
"""

import threading

from app.providers import harness
from app.providers import resident as resident_module
from app.tests.harness_fixtures import row


class _Profile:
    wire = "acp"
    argv = ("fake",)
    cwd = "."


class _WarmRecorder:
    def __init__(self) -> None:
        self.calls = []
        self.done = threading.Event()

    def warm(self, profile, *, timeout=15.0):
        self.calls.append((profile, timeout))
        self.done.set()
        return True


class _BrokenWarm:
    def warm(self, profile, *, timeout=15.0):
        raise RuntimeError("cannot start")


def test_a_resident_agent_is_warmed_once_before_the_answer(monkeypatch):
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    recorder = _WarmRecorder()
    monkeypatch.setattr(researcher, "_resident_profile", lambda: _Profile())
    monkeypatch.setattr(resident_module, "transport", lambda: recorder)

    researcher._start_warm()
    researcher._start_warm()  # once per turn: a second attempt saves nothing

    assert recorder.done.wait(2.0), "no worker was warmed"
    assert len(recorder.calls) == 1
    assert recorder.calls[0][1] == harness.RESIDENT_START_SECONDS


def test_an_agent_without_a_resident_protocol_is_not_warmed(monkeypatch):
    researcher = harness.HarnessResearcher(row("codex"))
    recorder = _WarmRecorder()
    monkeypatch.setattr(resident_module, "transport", lambda: recorder)

    researcher._start_warm()

    assert not recorder.done.wait(0.2), "Codex has no resident worker to warm"


def test_a_warm_up_that_cannot_start_costs_only_its_cold_start(monkeypatch):
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    monkeypatch.setattr(researcher, "_resident_profile", lambda: _Profile())
    monkeypatch.setattr(resident_module, "transport", lambda: _BrokenWarm())

    researcher._start_warm()  # must not raise, and must not wedge the turn
