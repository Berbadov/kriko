"""A resident turn cut off by its clock keeps the text that had arrived.

The reader's own run history: Mistral Vibe and Claude Code turns that outlived
the call's ceiling ended as ``DeliveryUncertain: the session timed out; worker
quarantined`` — with the answer already streamed to the screen. Nothing was
wrong with the words; the turn's clock was. The transport still quarantines the
worker (its turn may land later), but the prose the reader watched arrive is
kept, the same rule the API plane follows for a cut-off reply.
"""

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


def test_nothing_is_invented_when_no_text_arrived(monkeypatch):
    researcher = _researcher(monkeypatch, "")

    with pytest.raises(DeliveryUncertain):
        researcher._run_resident("Fiat Egea sorunları")
