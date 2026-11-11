"""The gate's default load, observed by running its stages against stand-ins.

The gate used to start all five stages at once, with pytest on every core and
cargo on every core, and that made a developer's machine unusable while it ran.
These tests run `tools/gate.sh` for real, but with a fake interpreter and a fake
cargo that only record what they were asked to do. Nothing is compiled, linted
or tested, so the tests cost almost nothing to run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _bash() -> str:
    """The bash the gate runs under: Git Bash on Windows, never WSL's."""
    if sys.platform == "win32":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            return str(git_bash)
    else:
        found = shutil.which("bash")
        if found:
            return found
    pytest.skip("tools/gate.sh runs under bash (Git Bash on Windows); none was found")


def _stand_in(path: Path, body: str) -> Path:
    """An executable script with `body`. Bash makes it executable, which Python cannot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
    subprocess.run([_bash(), "-c", 'chmod +x "$1"', "_", path.as_posix()], check=True)
    return path


def _run_gate(tmp_path: Path, stage: str, *, extra_env: dict[str, str] | None = None,
              path_prefix: Path | None = None) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run `tools/gate.sh <stage>` with a recording interpreter; return its result and calls."""
    log = tmp_path / "python-calls.log"
    python = _stand_in(tmp_path / "fakepy", f'echo "$@" >> "{log.as_posix()}"\nexit 0')
    # Only the gate's own knobs come from the caller, so a developer's GATE_JOBS
    # cannot change what these tests are asserting about the defaults.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GATE_", "KRIKO_GATE", "CARGO_BUILD_JOBS", "PYTHON"))}
    env["PYTHON"] = python.as_posix()
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    env.update(extra_env or {})
    result = subprocess.run([_bash(), "tools/gate.sh", stage], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=300)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


def test_the_python_stage_runs_pytest_on_two_workers_by_default(tmp_path):
    result, calls = _run_gate(tmp_path, "py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-m pytest -n 2" in calls, calls


def test_gate_jobs_auto_still_hands_pytest_every_core(tmp_path):
    result, calls = _run_gate(tmp_path, "py", extra_env={"GATE_JOBS": "auto"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-m pytest -n auto" in calls, calls


def test_the_cargo_stage_compiles_on_two_jobs_by_default(tmp_path):
    cargo_log = tmp_path / "cargo-calls.log"
    _stand_in(tmp_path / "bin" / "cargo",
              f'echo "jobs=${{CARGO_BUILD_JOBS:-unset}} $*" >> "{cargo_log.as_posix()}"\nexit 0')
    result, _ = _run_gate(tmp_path, "tauri", path_prefix=tmp_path / "bin")
    # 3 is the gate's own "skipped" (no Windows cross target off a Windows host);
    # it is not a failure, and the compile jobs are what this test is about.
    assert result.returncode in (0, 3), result.stdout + result.stderr
    cargo_calls = cargo_log.read_text(encoding="utf-8").splitlines()
    assert cargo_calls, "the gate never called cargo"
    assert all(line.startswith("jobs=2 ") for line in cargo_calls), cargo_calls
