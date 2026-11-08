"""The CLI adaptation layer: notice a changed CLI, and ask CLIs less.

`cliprobe` persists probe answers beside the store, keyed by the binary's
stamp (mtime + size). Two behaviours follow, and both are pinned here: an
unchanged binary is never probed again (across restarts), and a changed one
is re-probed, so every capability derived from its answer adapts. The
run-level half is `_invoke`'s one retry on the plain vector when the CLI
rejects the probed flags at argument-parsing time.
"""

import os
import time

import pytest

from app.providers import cliprobe, harness, hostbin
from app.providers.harness import Harness


@pytest.fixture
def fake_cli(tmp_path):
    """A runnable fake CLI whose content — and so stamp — a test can change."""
    exe = tmp_path / "fakecli"
    exe.write_text("#!/bin/sh\necho '--model m1'\n", encoding="utf-8")
    exe.chmod(0o755)
    return str(exe)


@pytest.fixture(autouse=True)
def clean_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("KRIKO_PROBE_STORE", str(tmp_path / "probes.json"))
    monkeypatch.setattr(harness, "_HELP", {})
    monkeypatch.setattr(harness, "_DECLARED", {})
    monkeypatch.setattr(harness, "_HELP_STAMP", {})
    monkeypatch.setattr(harness, "_HELP_FAILED", {})
    monkeypatch.setattr(harness, "_MODELS", {})
    monkeypatch.setattr(harness, "_EFFORTS", {})


def _rewrite(fake_cli, text):
    """Change the binary's bytes and its mtime, the way an update does."""
    with open(fake_cli, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.utime(fake_cli, (time.time() + 2, time.time() + 2))


def test_an_unchanged_cli_is_not_probed_again_across_restarts(fake_cli, monkeypatch):
    """A persisted answer is served without spawning any process."""
    cliprobe.record(fake_cli, "help", {"text": "--model m1", "declared": ["--model"]})
    monkeypatch.setattr(
        harness, "_ask",
        lambda *a, **k: pytest.fail("a persisted answer must not re-probe"),
    )
    assert harness.helptext(fake_cli) == "--model m1"
    assert harness.declared(fake_cli) == frozenset({"--model"})


def test_a_changed_cli_is_reasked_and_its_flags_change(fake_cli, monkeypatch):
    """A new binary is a new key: the old answer is dropped and re-probed."""
    cliprobe.record(fake_cli, "help", {"text": "--model m1", "declared": ["--model"]})
    _rewrite(fake_cli, "#!/bin/sh\necho '--effort low high'\n")
    assert cliprobe.entry(fake_cli, "help") is None
    answers = iter(["--effort low high"])
    monkeypatch.setattr(harness, "_ask", lambda *a, **k: next(answers))
    assert harness.helptext(fake_cli) == "--effort low high"
    assert harness.declared(fake_cli) == frozenset({"--effort"})
    # And the new answer is the one persisted now.
    assert cliprobe.entry(fake_cli, "help")["help"]["declared"] == ["--effort"]


def test_a_changed_cli_also_invalidates_models_and_efforts(fake_cli, monkeypatch):
    cliprobe.record(fake_cli, "models", ["m1"])
    cliprobe.record(fake_cli, "efforts", ["low"])
    _rewrite(fake_cli, "#!/bin/sh\necho changed\n")
    assert cliprobe.entry(fake_cli, "models") is None
    assert cliprobe.entry(fake_cli, "efforts") is None


def test_models_survive_a_restart_only_inside_their_ttl(fake_cli):
    cliprobe.record(fake_cli, "models", ["m1"])
    assert cliprobe.entry(fake_cli, "models")["models"] == ["m1"]
    store = cliprobe.store_path()
    data = __import__("json").loads(store.read_text(encoding="utf-8"))
    # Each kind keeps its own age, so a later `--help` probe cannot make an
    # old model list look fresh.
    data["probes"][fake_cli]["at_models"] = time.time() - harness.MODELS_TTL - 1
    store.write_text(__import__("json").dumps(data), encoding="utf-8")
    assert cliprobe.entry(fake_cli, "models") is not None
    # `entry` itself is stamp-based; the TTL is the reader's call — the age
    # travels with the payload so the reader can apply it.
    assert time.time() - cliprobe.entry(fake_cli, "models")["at"] > harness.MODELS_TTL


def test_ask_many_runs_every_question_in_one_harness_process(monkeypatch):
    calls = []

    def fake_probe(jobs, *, env, seconds):
        calls.append(jobs)
        return {
            "help": {"ok": True, "text": "--model m1"},
            "models": {"ok": True, "text": "openai/gpt-5\n"},
            "version": {"ok": False, "reason": "timed out"},
        }

    monkeypatch.setattr(hostbin, "probe", fake_probe)
    answered = cliprobe.ask_many(
        "/usr/bin/fakecli",
        {"help": ["--help"], "models": ["models"], "version": ["--version"]},
        keep=100, seconds=5.0,
    )
    assert len(calls) == 1
    assert {job["key"] for job in calls[0]} == {"help", "models", "version"}
    assert all(job["argv"][0] == "/usr/bin/fakecli" for job in calls[0])
    assert answered == {"help": "--model m1", "models": "openai/gpt-5\n"}


def test_ask_many_without_the_harness_binary_returns_none(monkeypatch):
    monkeypatch.setattr(hostbin, "probe", lambda *a, **k: None)
    assert cliprobe.ask_many("/usr/bin/fakecli", {"help": ["--help"]},
                             keep=100, seconds=5.0) is None


def test_command_for_can_force_the_plain_vector(monkeypatch):
    one = Harness(
        "fake", "Fake", "fakecli",
        args=("--stream", "--bogus"),
        plain_args=("run",),
        needs_in_help="--stream",
        structured=False,
    )
    monkeypatch.setitem(harness._HELP, "fakecli", "--stream")
    monkeypatch.setitem(harness._DECLARED, "fakecli", frozenset({"--stream"}))
    assert harness.command_for(one) == ["fakecli", "--stream", "--bogus"]
    assert harness.command_for(one, force_plain=True) == ["fakecli", "run"]


def test_a_run_rejected_on_arguments_is_retried_once_with_the_plain_vector(monkeypatch):
    one = Harness(
        "fake", "Fake", "fakecli",
        args=("--bogus",),
        plain_args=("run",),
        needs_in_help="--stream",
        structured=False,
    )
    monkeypatch.setitem(harness._HELP, "fakecli", "--stream")
    monkeypatch.setitem(harness._DECLARED, "fakecli", frozenset({"--stream"}))
    researcher = harness.HarnessResearcher(one)
    seen = []

    def fake_stream(command, stdin, say, **kwargs):
        seen.append(list(command))
        if "--bogus" in command:
            return 2, "", "error: unknown option `--bogus`\nUsage: fakecli [options]"
        return 0, "the answer", ""

    monkeypatch.setattr(researcher, "_stream", fake_stream)
    said = []
    assert researcher._invoke("brief", said.append) == "the answer"
    assert seen == [["fakecli", "--bogus", "--", "brief"], ["fakecli", "run", "--", "brief"]]
    assert any("plain mode" in line for line in said)


def test_a_run_that_fails_for_a_real_reason_is_not_retried(monkeypatch):
    one = Harness(
        "fake", "Fake", "fakecli",
        args=("--bogus",),
        plain_args=("run",),
        needs_in_help="--stream",
        structured=False,
    )
    monkeypatch.setitem(harness._HELP, "fakecli", "--stream")
    monkeypatch.setitem(harness._DECLARED, "fakecli", frozenset({"--stream"}))
    researcher = harness.HarnessResearcher(one)
    seen = []

    def fake_stream(command, stdin, say, **kwargs):
        seen.append(list(command))
        return 1, "", "Invalid API key provided"

    monkeypatch.setattr(researcher, "_stream", fake_stream)
    with pytest.raises(RuntimeError, match="Invalid API key"):
        researcher._invoke("brief", None)
    assert len(seen) == 1
