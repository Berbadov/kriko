"""A test may not write to the reader's own ~/.kriko.

Found while landing B70: `test_web.py`'s `client` fixture passed a
`store_path` and an `analysis_log_path` into `Settings` and left
`app_state_path` at its default — which is `~/.kriko/app.sqlite`, the
developer's real one. Fifty-four tests had been writing their history rows,
their marks, their extension sightings and (once B70 landed) their unmapped
labels into it, and the way it surfaced was a count that started at eleven.

Nothing failed, which is the whole pattern this branch keeps finding: the
tests passed, the assertions were about the response rather than the row, and
the leak was only visible to an assertion about an accumulated total.

So this is the gate rather than a fix to one fixture. It is a guard on
`state.connect`, the single door to `app.sqlite`, so a fixture added next
month is covered without being told: any test that opens the app state under
the reader's home fails, and says which path and what to pass instead.

Deliberately not a redirect. Silently rewriting the path would make the tests
pass while leaving the next fixture written the same way — and a fixture that
does not say where its state lives is the bug, not the path.
"""

from pathlib import Path

import pytest

#: The reader's own directory. Resolved once, at import: a test that changes
#: `HOME` mid-run must not be able to step outside the guard.
FORBIDDEN = (Path.home() / ".kriko").resolve()


@pytest.fixture(autouse=True)
def no_writes_to_the_readers_home(monkeypatch):
    from app.web import state

    real = state.connect

    def guarded(path, *args, **kwargs):
        try:
            resolved = Path(path).resolve()
        except (OSError, TypeError, ValueError):
            resolved = None
        if resolved is not None and resolved.is_relative_to(FORBIDDEN):
            raise AssertionError(
                f"a test opened the reader's own app state at {resolved}. "
                "Pass app_state_path=tmp_path / 'app.sqlite' to Settings — "
                "see src/app/tests/conftest.py."
            )
        return real(path, *args, **kwargs)

    monkeypatch.setattr(state, "connect", guarded)
    yield


@pytest.fixture(autouse=True)
def no_test_starts_a_real_coding_agent(monkeypatch):
    """A test may not spawn the reader's actual agent CLI.

    The sibling of the guard above, found the same way. `tasks.default_backend()`
    resolves an unnamed plane to `harness` whenever a coding-agent CLI is on
    PATH — which is right for the app and a trap for the suite: on a developer's
    machine `test_a_real_agenda_run_ends_up_in_the_run_list` posted no backend,
    got `harness`, and spent fifteen seconds driving a real `claude` against the
    reader's subscription before the deadline killed it. On CI, where no CLI is
    installed, it passed. That asymmetry is how a test ends up billing somebody.

    So the door is shut at the one place a harness plane actually starts a
    process — and shut on *which* process rather than on the call, because
    `test_the_harness_research_plane.py` drives the real `_run` on purpose
    against a fake CLI it writes into `tmp_path`. That is the distinction worth
    encoding: a harness test should exercise the spawn, and no test should
    exercise the reader's own agent.

    The line is `harness.KNOWN` — the executables Kriko would really drive. A
    fixture names `sys.executable` and a script it just wrote, so it passes;
    `claude` never does, whether it is installed here or not.
    """
    from app.providers import harness

    real = harness.HarnessResearcher._run
    theirs = {h.executable for h in harness.KNOWN}

    def guarded(self, prompt):
        executable = str(getattr(self.harness, "executable", ""))
        if Path(executable).name in theirs:
            raise AssertionError(
                f"a test tried to start {executable!r}, the reader's own coding "
                "agent. Name a plane (`backend: 'agent'`), or point the harness "
                "at a fake CLI as `_fake_cli` does.")
        return real(self, prompt)

    monkeypatch.setattr(harness.HarnessResearcher, "_run", guarded)
