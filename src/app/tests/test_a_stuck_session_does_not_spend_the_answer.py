"""A stuck hosted session must not spend the answer's budget.

`session/new` used to wait on the turn's own deadline, so a stuck ACP build ate
the whole answer before the fresh-process fallback could start — the 102-second
Mistral turn in the reader's field log. The request now carries a start
allowance, shorter than the turn, so the fallback inherits the rest.
"""

from app.providers import harness
from app.providers import resident as resident_module
from app.providers.resident import ResidentResult
from app.tests.harness_fixtures import row


class _Profile:
    wire = "acp"
    argv = ("fake",)
    cwd = "."


class _RecordingTransport:
    def __init__(self) -> None:
        self.requests = []

    def run(self, profile, request):
        self.requests.append(request)
        return ResidentResult("answer", "", "", {}, {}, {})


def test_an_agent_session_is_given_a_shorter_start_allowance_than_its_turn(monkeypatch):
    researcher = harness.HarnessResearcher(row("mistral-vibe"))
    transport = _RecordingTransport()
    monkeypatch.setattr(researcher, "_resident_profile", lambda: _Profile())
    monkeypatch.setattr(resident_module, "transport", lambda: transport)

    researcher._run_resident("hello")

    request = transport.requests[0]
    assert request.start_timeout == harness.RESIDENT_START_SECONDS
    assert request.start_timeout < request.timeout
