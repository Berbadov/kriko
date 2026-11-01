"""The Rust helper, called the way the app calls it: through `harness`."""

import os
import stat
import time
from pathlib import Path

import pytest

from app.providers import harness, hostbin

BUILT = Path(__file__).resolve().parents[3] / "kriko-harness" / "target"
HELPER = next((p for kind in ("release", "debug") if (p := BUILT / kind / "kriko-harness").is_file()), None)
pytestmark = pytest.mark.skipif(HELPER is None or os.name == "nt", reason="cargo build in kriko-harness first")


@pytest.fixture(autouse=True)
def the_helper(monkeypatch):
    monkeypatch.setattr(hostbin, "binary", lambda: str(HELPER))


def _cli(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_help_text_comes_back_through_the_helper(tmp_path):
    cli = _cli(tmp_path, "agent", "echo '--model <name>'; echo oops >&2")
    assert harness._ask(str(cli), "--help") == "--model <name>\noops\n"


def test_a_hung_cli_reads_as_saying_nothing_at_its_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "HELP_TIMEOUT_SECONDS", 1.0)
    cli = _cli(tmp_path, "agent", "sleep 30")
    started = time.monotonic()
    assert harness._ask(str(cli), "--help") == ""
    assert time.monotonic() - started < 3


def test_every_missing_cli_is_found_in_one_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv(harness.DIRS_ENV, raising=False)
    monkeypatch.setattr(harness.Path, "home", staticmethod(lambda: tmp_path))
    _cli(tmp_path / ".local" / "bin", "claude", "exit 0")
    _cli(tmp_path / ".local" / "bin", "codex", "exit 0")
    calls: list[int] = []
    real = hostbin.locate
    monkeypatch.setattr(hostbin, "locate", lambda items, **kw: calls.append(len(items)) or real(items, **kw))

    assert {h.id for h in harness.available()} >= {"claude-code", "codex"}
    assert calls == [len(harness.KNOWN)]
