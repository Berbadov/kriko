"""A CLI that was slow once is not a CLI that declares no flags.

The reader's chat failed for two agents at once: "Claude Code does not declare
per-run model selection" and "Antigravity CLI lacks required flags:
--output-format". Both CLIs list those flags. The first `--help` probe of each
had come back empty (a slow first start, or a probe that queued behind others
and gave up), and the empty answer was remembered until the app was closed.
"""

from app.providers import harness

EXE = "C:/tools/fake-agent.exe"
HELP = "Usage: fake\n  --model <model>   the model\n  --output-format <f>  the format\n"


def _fresh(monkeypatch):
    for name in ("_HELP", "_DECLARED", "_HELP_FAILED"):
        monkeypatch.setattr(harness, name, {})


def test_an_empty_probe_is_not_remembered_as_what_the_cli_declares(monkeypatch):
    _fresh(monkeypatch)
    answers = iter(["", HELP])
    monkeypatch.setattr(harness, "_ask", lambda *a, **k: next(answers))
    clock = [1000.0]
    monkeypatch.setattr(harness.time, "monotonic", lambda: clock[0])

    assert harness.declared(EXE) == frozenset()

    clock[0] += harness.HELP_RETRY_SECONDS + 1
    assert {"--model", "--output-format"} <= harness.declared(EXE)


def test_a_probe_that_said_nothing_is_not_asked_again_in_the_same_breath(monkeypatch):
    _fresh(monkeypatch)
    calls = []
    monkeypatch.setattr(harness, "_ask", lambda *a, **k: calls.append(a) or "")
    clock = [1000.0]
    monkeypatch.setattr(harness.time, "monotonic", lambda: clock[0])

    for _ in range(5):
        harness.declared(EXE)

    assert len(calls) == 1, "every screen that lists the planes would wait on a dead CLI"


def test_an_answer_is_kept(monkeypatch):
    _fresh(monkeypatch)
    calls = []
    monkeypatch.setattr(harness, "_ask", lambda *a, **k: calls.append(a) or HELP)

    harness.declared(EXE)
    harness.declared(EXE)

    assert len(calls) == 1
