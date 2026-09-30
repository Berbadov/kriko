"""Finding the reader's coding-agent CLI when `PATH` does not carry it.

B108's live report was "agent operations do nothing". `PATH` is the reason
that can happen with no error anywhere: `available()` returns `[]`, the
harness plane reports itself not ready, and there is nothing for any screen to
say because nothing in the process knows a CLI exists.

The sidecar's `PATH` is the one the file manager handed the desktop shell at
*login*. A reader who installs Claude Code and comes straight back to Kriko
has the binary on disk and not on that `PATH`.
"""

import os
import stat

import pytest

from app.providers import harness


def _fake_cli(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def nowhere_on_path(monkeypatch, tmp_path):
    """A PATH with nothing on it, which is the failure being reproduced."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv(harness.DIRS_ENV, raising=False)
    monkeypatch.setattr(harness, "_DECLARED", {})
    return tmp_path


def test_a_cli_off_the_path_is_still_found_where_it_installs_itself(
    nowhere_on_path, monkeypatch
):
    home = nowhere_on_path / "home"
    _fake_cli(home / ".local" / "bin", "claude")
    monkeypatch.setattr(harness.Path, "home", staticmethod(lambda: home))

    claude = next(h for h in harness.KNOWN if h.id == "claude-code")
    assert harness.locate(claude).endswith(os.path.join(".local", "bin", "claude"))
    assert [h.id for h in harness.available()] == ["claude-code"]


def test_the_escape_hatch_is_one_environment_variable(
    nowhere_on_path, monkeypatch
):
    """A reader whose install is somewhere none of the rules predict."""
    odd = nowhere_on_path / "somewhere" / "odd"
    _fake_cli(odd, "claude")
    monkeypatch.setattr(harness.Path, "home", staticmethod(lambda: nowhere_on_path))
    monkeypatch.setenv(harness.DIRS_ENV, str(odd))

    claude = next(h for h in harness.KNOWN if h.id == "claude-code")
    assert harness.locate(claude) == str(odd / "claude")


def test_nothing_anywhere_is_an_empty_answer_not_a_crash(
    nowhere_on_path, monkeypatch
):
    monkeypatch.setattr(harness.Path, "home", staticmethod(lambda: nowhere_on_path))
    assert harness.available() == []
    claude = next(h for h in harness.KNOWN if h.id == "claude-code")
    assert harness.locate(claude) == ""


def test_the_command_runs_the_binary_that_was_found(nowhere_on_path, monkeypatch):
    """Not the bare name. A name that `PATH` could not resolve for `which`
    will not resolve for `subprocess` either."""
    home = nowhere_on_path / "home"
    cli = _fake_cli(home / ".local" / "bin", "claude")
    monkeypatch.setattr(harness.Path, "home", staticmethod(lambda: home))

    claude = next(h for h in harness.KNOWN if h.id == "claude-code")
    assert harness.command_for(claude)[0] == str(cli)


def test_a_pathext_match_is_shown_in_lower_case(monkeypatch):
    """settings-23: `shutil.which` on Windows returns whatever case PATHEXT
    is spelled in (conventionally upper case, ".COM;.EXE;.BAT;.CMD"), and
    Settings prints `locate`'s return value verbatim — so an npm-installed
    CLI read "...\\claude.CMD" next to every other path's lower-case
    extension. Cosmetic (Windows paths are case-insensitive either way), but
    the one path a reader actually looks at should not be the odd one out.
    """
    monkeypatch.setattr(harness.os, "name", "nt")
    # Flipping `os.name` to "nt" also flips which `pathlib` class `Path()`
    # builds, and `locate()` calls `Path.home()` for its cache key: on a
    # Linux runner the Windows flavour then reads `USERPROFILE`, and with
    # that unset Python 3.12 raises "Could not determine home directory" —
    # a platform this test does not otherwise touch (the same pitfall the
    # harness plane's own docstring names at test_the_cmd_shim_is_actually
    # _handed_to_popen_with_shell_true). Set the env the flavour reads, or
    # the test cannot run anywhere but Windows.
    monkeypatch.setenv("USERPROFILE", r"C:\Users\reader")
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(
        harness.shutil, "which", lambda executable: r"C:\Users\reader\claude.CMD"
    )

    claude = next(h for h in harness.KNOWN if h.id == "claude-code")
    assert harness.locate(claude) == r"C:\Users\reader\claude.cmd"
