"""An agent installed after Kriko started is still found, and still starts.

The desktop app inherits the PATH of the login it was started from. A CLI the
reader installs afterwards is on the registry's PATH only, so the lookup has to
read what the next login will read, and the process an agent runs in has to
carry it too, or the agent is found and then cannot find its own runtime.
"""

import os
import stat

import pytest

from app import loginpath
from app.providers import harness


@pytest.fixture(autouse=True)
def _fresh_lookup():
    harness.forget_located()
    yield
    harness.forget_located()


def _fake_cli(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (f"{name}.exe" if os.name == "nt" else name)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_the_registry_folders_follow_the_process_path_without_repeats(monkeypatch):
    monkeypatch.setattr(loginpath, "_registry_path_values", lambda: [os.pathsep.join(["/a", "/b"]), "/c"])
    got = loginpath.login_path(os.pathsep.join(["/b", "/z"])).split(os.pathsep)
    assert got == ["/b", "/z", "/a", "/c"]


def test_a_registry_value_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("KRIKO_TEST_ROOT", str(tmp_path))
    spelled = "%KRIKO_TEST_ROOT%" + os.sep + "bin" if os.name == "nt" else "$KRIKO_TEST_ROOT/bin"
    monkeypatch.setattr(loginpath, "_registry_path_values", lambda: [spelled])
    assert str(tmp_path / "bin") in loginpath.login_path("").split(os.pathsep)


def test_a_cli_installed_after_the_app_started_is_found(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv(harness.DIRS_ENV, raising=False)
    cli = _fake_cli(tmp_path / "somewhere" / "nobody-lists", "claude")
    one = next(h for h in harness.KNOWN if h.id == "claude-code")
    monkeypatch.setattr(loginpath, "_registry_path_values", lambda: [])
    assert harness.locate(one) == ""
    harness.forget_located()
    monkeypatch.setattr(loginpath, "_registry_path_values", lambda: [str(cli.parent)])
    assert os.path.normcase(harness.locate(one)) == os.path.normcase(str(cli))


def test_the_process_an_agent_runs_in_carries_the_fresh_path_and_its_own_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(loginpath, "_registry_path_values", lambda: [str(tmp_path / "node")])
    env = loginpath.child_env({"PATH": str(tmp_path / "old")}, extra_dirs=(str(tmp_path / "cli"),))
    folders = env["PATH"].split(os.pathsep)
    assert folders == [str(tmp_path / "cli"), str(tmp_path / "old"), str(tmp_path / "node")]
