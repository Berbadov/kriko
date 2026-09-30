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


@pytest.fixture(autouse=True, scope="session")
def the_app_log_is_not_the_readers(tmp_path_factory):
    """The one redirect here, because no fixture *can* say where this lives.

    `create_app` attaches a process-wide rotating handler at `KRIKO_LOG`, else
    `~/.kriko/logs/app.log`, and `Settings` has no field for it. So every test
    that built an app appended to the reader's log — and on Windows, where the
    installed Kriko holds that file open, each rollover failed with WinError 32
    inside `create_app` and the suite stalled there.
    """
    import os

    from app import logs

    before = os.environ.get("KRIKO_LOG")
    os.environ["KRIKO_LOG"] = str(tmp_path_factory.mktemp("logs") / "app.log")
    logs.reset_for_tests()
    yield
    logs.reset_for_tests()
    if before is None:
        os.environ.pop("KRIKO_LOG", None)
    else:
        os.environ["KRIKO_LOG"] = before


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


@pytest.fixture(autouse=True)
def no_attaching_to_the_readers_own_engine(monkeypatch):
    """A test may not find the engine the developer has running.

    The third instance of the same shape as the two guards above, and it cost
    two false gate failures before it was written. `attach()` scans
    `DEFAULT_PORTS` — the one fixed port the extension is allowed to assume —
    so three `test_cli.py` cases that assert what the CLI does with *no engine
    running* were instead asking whatever was serving on 8787. On a clean
    machine they pass. On the machine of anybody who has the app open while
    they work, which is everybody working on the app, they fail with somebody
    else's sites and somebody else's operations in the diff.

    Worse than the failure is the direction it could have gone: a test that
    *passes* because a live engine answered is a test that proves nothing, and
    nothing about it would look wrong.

    So the default port list is empty under test. A test that wants an engine
    starts its own — `serve_in_thread` exists for exactly that and takes its
    own `Settings` — and a test that passes an explicit `url` is untouched,
    because that is a deliberate address rather than a scan.
    """
    from app.tui import client

    monkeypatch.setattr(client, "DEFAULT_PORTS", ())
    monkeypatch.delenv("KRIKO_URL", raising=False)


@pytest.fixture(autouse=True)
def no_test_asks_a_real_provider_for_its_models(monkeypatch):
    """A test may not call a vendor's `/models` with whatever key it set.

    Same shape as the guards above. `/api/prefs` starts a background
    `modeldiscovery.refresh` whenever a completion key is present, and plenty
    of tests set a fake one — which would send it to api.openai.com. A test
    that wants discovery calls `modeldiscovery.ask` with its own `opener`.
    """
    from app import modeldiscovery

    monkeypatch.setattr(modeldiscovery, "refresh", lambda: {})
    monkeypatch.setattr(modeldiscovery, "_refresh_in_background", lambda: None)
    monkeypatch.setattr(modeldiscovery, "_CACHE", {})


@pytest.fixture(autouse=True)
def every_test_finds_the_clis_afresh(monkeypatch):
    """`harness.locate` remembers for a few seconds (B152.7); one test's fake
    CLI on disk must not be another test's installed one."""
    from app.providers import harness

    monkeypatch.setattr(harness, "_LOCATED", {})


@pytest.fixture(autouse=True)
def the_weekly_pack_update_stays_off(monkeypatch):
    """Entering a lifespan must not fetch the real pack index (B166).

    `app.packautoupdate` submits a background job at startup. A test that
    wants to exercise it calls `submit_if_due` itself against a local server.
    """
    monkeypatch.setenv("KRIKO_NO_PACK_AUTOUPDATE", "1")
