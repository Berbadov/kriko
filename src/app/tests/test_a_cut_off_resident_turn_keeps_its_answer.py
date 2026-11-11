"""A resident turn cut off by its clock keeps the text that had arrived.

The reader's own run history: Mistral Vibe and Claude Code turns that outlived
the call's ceiling ended as ``DeliveryUncertain: the session timed out; worker
quarantined`` — with the answer already streamed to the screen. Nothing was
wrong with the words; the turn's clock was. The transport still quarantines the
worker (its turn may land later), but the prose the reader watched arrive is
kept, the same rule the API plane follows for a cut-off reply.
"""

import contextlib

import pytest

from app.providers import harness
from app.providers import resident as resident_module
from app.providers.codex_transport import DeliveryUncertain
from app.tests.harness_fixtures import row


class _Profile:
    wire = "acp"
    argv = ("fake",)
    cwd = "."


class _CutOffTransport:
    """Streams a fragment, then reports the turn as delivery-uncertain."""

    def __init__(self, streamed: str) -> None:
        self.streamed = streamed
        self.requests = []

    def run(self, profile, request):
        self.requests.append(request)
        if self.streamed:
            request.on_text(self.streamed)
        raise DeliveryUncertain("the session timed out; worker quarantined")


def _researcher(monkeypatch, streamed: str):
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    transport = _CutOffTransport(streamed)
    monkeypatch.setattr(researcher, "_resident_profile", lambda: _Profile())
    monkeypatch.setattr(resident_module, "transport", lambda: transport)
    return researcher


def test_the_text_that_arrived_is_kept(monkeypatch):
    researcher = _researcher(monkeypatch, "The EGR valve clogs on the 1.3 MultiJet.")

    answer = researcher._run_resident("Fiat Egea sorunları")

    assert answer == "The EGR valve clogs on the 1.3 MultiJet."
    assert researcher.telemetry.get("cut_off") is True


@pytest.fixture(autouse=True)
def _clean_resident_health():
    harness._RESIDENT_UNHEALTHY.clear()
    yield
    harness._RESIDENT_UNHEALTHY.clear()


def test_a_timeout_with_no_text_marks_the_harness_unhealthy(monkeypatch):
    researcher = _researcher(monkeypatch, "")

    with pytest.raises(DeliveryUncertain):
        researcher._run_resident("a product question")

    assert harness._resident_unhealthy(researcher.harness)


def test_a_timeout_that_kept_text_does_not_mark_the_harness(monkeypatch):
    researcher = _researcher(monkeypatch, "The EGR valve clogs on the 1.3 MultiJet.")

    researcher._run_resident("a product question")

    assert not harness._resident_unhealthy(researcher.harness)


def _auto_researcher(monkeypatch, *, calls):
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    researcher.transport_mode = "auto"
    monkeypatch.setattr(researcher, "_can_converse", lambda: False)
    monkeypatch.setattr(researcher, "_workspace", lambda: contextlib.nullcontext())

    def _resident(prompt, on_line=None):
        calls.append("resident")
        raise AssertionError("the marked harness must not use the resident worker")

    def _invoke(prompt, on_line=None):
        calls.append("process")
        return "a fresh-process answer"

    monkeypatch.setattr(researcher, "_run_resident", _resident)
    monkeypatch.setattr(researcher, "_invoke", _invoke)
    return researcher


def test_a_marked_harness_runs_a_fresh_process_in_auto_mode(monkeypatch):
    calls: list[str] = []
    researcher = _auto_researcher(monkeypatch, calls=calls)
    harness._mark_resident_unhealthy(researcher.harness)

    assert researcher._run_once("a product question") == "a fresh-process answer"
    assert calls == ["process"]


def test_an_unmarked_harness_still_uses_the_resident_worker(monkeypatch):
    calls: list[str] = []
    researcher = _auto_researcher(monkeypatch, calls=calls)
    researcher._run_resident = lambda prompt, on_line=None: calls.append("resident") or "ok"

    assert researcher._run_once("a product question") == "ok"
    assert calls == ["resident"]


def test_explicit_persistent_mode_still_uses_the_resident_worker(monkeypatch):
    calls: list[str] = []
    researcher = _auto_researcher(monkeypatch, calls=calls)
    researcher.transport_mode = "persistent"
    harness._mark_resident_unhealthy(researcher.harness)
    researcher._run_resident = lambda prompt, on_line=None: calls.append("resident") or "ok"

    assert researcher._run_once("a product question") == "ok"
    assert calls == ["resident"]


def test_nothing_is_invented_when_no_text_arrived(monkeypatch):
    researcher = _researcher(monkeypatch, "")

    with pytest.raises(DeliveryUncertain):
        researcher._run_resident("Fiat Egea sorunları")
