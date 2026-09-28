"""B151: opencode received the first line of every brief, then sat silent.

The reader's words: *"opencode isnt working at all."* Its own session store
held one user message per run — `"# Quick look: what is known to go wrong with
this one?"`, the brief's first line, twice — because the harness started it
through npm's `opencode.cmd`, and `cmd.exe` ends a command at a newline. And
it started in `~`, which on the reader's machine is a git repository that
opencode snapshots before its first model call.

Both stand-ins here run a real subprocess and read back what it was given.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from app.providers import harness as harness_mod
from app.providers.harness import HarnessResearcher, unshim

BRIEF = "# Quick look: what is known to go wrong with this one?\n\nAcme Roadster\n* km: 95.000"

windows = pytest.mark.skipif(os.name != "nt", reason="npm .cmd shims are a Windows file")


def _shim(directory: Path, target: str, *, node: bool = False) -> Path:
    """npm's cmd-shim, byte for byte in shape."""
    call = (f'"%_prog%"  "%dp0%\\{target}" %*' if node
            else f'"%dp0%\\{target}"   %*')
    shim = directory / "fake.cmd"
    shim.write_text(
        "@ECHO off\nGOTO start\n:find_dp0\nSET dp0=%~dp0\nEXIT /b\n:start\n"
        f"SETLOCAL\nCALL :find_dp0\n{call}\n", encoding="utf-8")
    return shim


@windows
def test_an_exe_shim_is_run_as_the_exe_it_wraps(tmp_path):
    real = tmp_path / "node_modules" / "cli" / "bin" / "tool.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"MZ")
    shim = _shim(tmp_path, r"node_modules\cli\bin\tool.exe")
    assert unshim([str(shim), "run", "--", BRIEF]) == [str(real), "run", "--", BRIEF]


@windows
def test_a_node_script_shim_is_run_by_node(tmp_path):
    script = tmp_path / "node_modules" / "cli" / "cli.js"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    (tmp_path / "node.exe").write_bytes(b"MZ")
    shim = _shim(tmp_path, r"node_modules\cli\cli.js", node=True)
    assert unshim([str(shim), "-p"]) == [str(tmp_path / "node.exe"), str(script), "-p"]


@windows
def test_anything_else_is_left_to_cmd_exe(tmp_path):
    odd = tmp_path / "odd.cmd"
    odd.write_text("@echo off\nsomething %*\n", encoding="utf-8")
    assert unshim([str(odd), "x"]) == [str(odd), "x"]
    missing = _shim(tmp_path, r"gone\tool.exe")
    assert unshim([str(missing), "x"]) == [str(missing), "x"]
    assert unshim(["C:\\bin\\tool.exe", "x"]) == ["C:\\bin\\tool.exe", "x"]


def _echo(tmp_path: Path) -> Path:
    script = tmp_path / "echo.py"
    script.write_text(
        "import json, os, sys\n"
        "print(json.dumps({'type': 'result', 'result': json.dumps({"
        "'argv': sys.argv[1:], 'cwd': os.getcwd(), 'files': os.listdir('.')})}))\n",
        encoding="utf-8")
    return script


@windows
def test_a_multi_line_brief_crosses_the_shim_whole(tmp_path):
    """The reader's failure, end to end: a real `.cmd` in front of a real
    program, a brief with newlines, and the program says what it got."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = os.path.relpath(sys.executable, bin_dir)
    shim = _shim(bin_dir, target)
    one = harness_mod.Harness("fake", "Fake CLI", str(shim), (str(_echo(tmp_path)),),
                              structured=True)
    got = json.loads(HarnessResearcher(one, timeout=30).ask(BRIEF))
    assert got["argv"][-1] == BRIEF


@windows
def test_a_brief_past_cmd_exes_limit_crosses_the_shim(tmp_path):
    """The deep run's failure (job `1065777c`): "opencode exited 1: The
    command line is too long." — cmd.exe stops at 8191 characters; a process
    started directly takes 32767, and briefs stay under
    `MAX_PROMPT_ARGUMENT`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = _shim(bin_dir, os.path.relpath(sys.executable, bin_dir))
    one = harness_mod.Harness("fake", "Fake CLI", str(shim), (str(_echo(tmp_path)),),
                              structured=True)
    brief = BRIEF + "\n" + "x" * 12000
    assert len(brief) < harness_mod.MAX_PROMPT_ARGUMENT
    got = json.loads(HarnessResearcher(one, timeout=30).ask(brief))
    assert got["argv"][-1] == brief


def test_a_run_starts_in_an_empty_directory_not_the_readers_home(tmp_path):
    one = harness_mod.Harness("fake", "Fake CLI", sys.executable, (str(_echo(tmp_path)),),
                              structured=True)
    got = json.loads(HarnessResearcher(one, timeout=30).ask("brief"))
    assert Path(got["cwd"]).resolve() != Path.home().resolve()
    assert got["files"] == []
