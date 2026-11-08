"""Mistral Vibe 3 is driven through the flags it declares, and fails in words.

Measured on the reader's machine on 2026-11-08 with Vibe 3.1.0 (a Rust client
over a Python app-server, three processes where 2.x was one):

* a model id from the picker with an effort chosen wrote `thinking` twice into
  the run's `config.toml`, and Vibe refused the file ("Cannot overwrite a
  value") before doing anything;
* the effort dial offered only `high`, so every chat-speed pass that asks for
  `low` ran at the reader's own `max` and spent the 90-second turn thinking;
* `mistral-small-latest` refuses `low` with a 400, so offering `low` needs the
  run to fall back to the model's own level rather than fail;
* a `402 Vibe budget exhausted` was read as "the hosted session is down", the
  session was benched for ten minutes and a fresh process paid the same 402.

Every test here is about Kriko's half of that boundary; none starts the CLI.
"""

import json
import os
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from app.providers import cliprobe
from app.providers import harness as harness_mod
from app.tests.harness_fixtures import row


def _vibe(**kwargs):
    return harness_mod.HarnessResearcher(
        replace(row("mistral-vibe"), executable=sys.executable), **kwargs)


@pytest.fixture(autouse=True)
def _fresh_memory(monkeypatch, tmp_path):
    monkeypatch.setattr(harness_mod, "_RESIDENT_UNHEALTHY", {})
    monkeypatch.setattr(harness_mod, "_REFUSED_EFFORTS", set())
    monkeypatch.setenv("KRIKO_PROBE_STORE", str(tmp_path / "cli-probes.json"))


# ── the run's config ─────────────────────────────────────────────────────────


def test_a_chosen_model_with_an_effort_writes_its_thinking_once(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / ".vibe").mkdir(parents=True)
    (home / ".vibe" / "config.toml").write_text(
        'active_model = "glm"\nmodels = [{ alias = "glm", thinking = "max" }]\n',
        encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    text, chosen = harness_mod._vibe_config(
        "brand-new-model", "low", tmp_path / "sessions", log_sessions=False)

    parsed = tomllib.loads(text)  # a repeated key raises here, as it did in Vibe
    rows = {r["alias"]: r for r in parsed["models"]}
    assert chosen == "brand-new-model"
    assert rows["brand-new-model"]["thinking"] == "low"
    # The reader's own row keeps the level they gave it.
    assert rows["glm"]["thinking"] == "max"


# ── the effort dial ──────────────────────────────────────────────────────────


def test_vibe_three_offers_the_levels_it_sends_as_written(monkeypatch):
    one = row("mistral-vibe")
    monkeypatch.setattr(harness_mod, "locate", lambda _one: "vibe")
    monkeypatch.setattr(harness_mod, "_cached_declared",
                        lambda _exe: frozenset({"--output-dir", "--time-limit", "--prompt"}))
    assert harness_mod.efforts_for(one) == list(harness_mod.VIBE3_EFFORTS)
    assert harness_mod.cached_efforts_for(one) == list(harness_mod.VIBE3_EFFORTS)


@pytest.mark.parametrize("known", [None, frozenset({"--prompt", "--output"})])
def test_vibe_two_or_an_unprobed_build_keeps_its_one_level(monkeypatch, known):
    one = row("mistral-vibe")
    monkeypatch.setattr(harness_mod, "locate", lambda _one: "vibe")
    monkeypatch.setattr(harness_mod, "_cached_declared", lambda _exe: known)
    assert harness_mod.efforts_for(one) == ["high"]


def test_a_level_the_model_refuses_is_retried_at_its_own_level_once(monkeypatch):
    researcher = _vibe(effort="low", model="small")
    seen = []

    def run_once(prompt, on_line=None):
        seen.append(researcher.requested_effort)
        if researcher.requested_effort:
            raise RuntimeError(
                "Mistral exited 2: Error: API error occurred: Status 400. Body: "
                "{\"message\":\"reasoning_effort='low' is not supported for this model\"}")
        return "answered"

    monkeypatch.setattr(researcher, "_run_once", run_once)
    said = []
    researcher.on_action = said.append

    assert researcher._run("brief") == "answered"
    assert seen == ["low", ""]
    assert "does not take effort 'low'" in " ".join(said)

    # The next run on the same model skips the refusal it already paid for.
    again = _vibe(effort="low", model="small")
    asked = []
    monkeypatch.setattr(again, "_run_once",
                        lambda prompt, on_line=None: asked.append(again.requested_effort) or "ok")
    assert again._run("brief") == "ok"
    assert asked == [""]


def test_any_other_failure_is_not_retried(monkeypatch):
    researcher = _vibe(effort="low")
    calls = []

    def run_once(prompt, on_line=None):
        calls.append(1)
        raise RuntimeError("Mistral exited 1: something else")

    monkeypatch.setattr(researcher, "_run_once", run_once)
    with pytest.raises(RuntimeError, match="something else"):
        researcher._run("brief")
    assert calls == [1]


# ── an account failure is not a transport failure ────────────────────────────


def test_a_billing_refusal_is_reported_not_replayed_in_a_fresh_process(monkeypatch):
    from app.providers.codex_transport import TurnRejected

    researcher = _vibe()
    researcher.transport_mode = "auto"

    def rejected(*_args, **_kwargs):
        raise TurnRejected(
            'API error occurred: Status 402. Body: {"message":"Vibe budget exhausted.",'
            '"type":"billing_vibe_budget_exhausted"}')

    monkeypatch.setattr(researcher, "_run_resident", rejected)
    monkeypatch.setattr(researcher, "_invoke", lambda *_a, **_k: pytest.fail(
        "a fresh process meets the same 402; it must not be started"))

    with pytest.raises(RuntimeError, match="cannot pay for this run"):
        researcher.ask("brief", allow_tools=False)
    assert researcher.harness.id not in harness_mod._RESIDENT_UNHEALTHY


@pytest.mark.parametrize("reason,account", [
    ("workspace routing discovery unauthorized (401)", True),
    ("Failed to refresh token ... Please log out and sign in again.", True),
    ("usage limit reached", True),
    ("[WinError 5] Access is denied", False),
    ("acp did not open a session in time", False),
])
def test_account_failures_are_told_apart_from_transport_ones(reason, account):
    assert harness_mod.account_failure(reason) is account


# ── the exec vector ──────────────────────────────────────────────────────────


def test_vibe_three_gets_an_export_folder_and_its_own_clock():
    researcher = _vibe(timeout=120)
    researcher._vibe_export = Path("x") / "export"
    args = researcher._vibe_run_args(frozenset({"--output-dir", "--time-limit"}))
    assert args[args.index("--output-dir") + 1] == str(Path("x") / "export")
    assert args[args.index("--time-limit") + 1] == str(int(120 - harness_mod.VIBE_TIME_LIMIT_MARGIN))
    # A build that declares neither is run exactly as before.
    assert researcher._vibe_run_args(frozenset()) == []


def test_the_prompt_goes_in_a_file_when_the_cli_takes_one(monkeypatch):
    researcher = _vibe(timeout=120)
    monkeypatch.setattr(harness_mod, "declared",
                        lambda _exe: frozenset({"--prompt", "--prompt-file"}))
    seen = {}

    def stream(command, stdin_read, say, opening=""):
        path = command[command.index("--prompt-file") + 1]
        seen.update(command=command, prompt=Path(path).read_text(encoding="utf-8"))
        line = {"type": "message", "role": "assistant", "generationStatus": "completed",
                "content": [{"type": "text", "text": "answer"}]}
        return 0, json.dumps(line), ""

    monkeypatch.setattr(researcher, "_stream", stream)
    assert researcher._invoke_with([sys.executable], "brief ÇĞŞ", None) == "answer"
    assert seen["prompt"] == "brief ÇĞŞ"
    assert "--prompt" not in seen["command"]
    assert not os.path.exists(seen["command"][seen["command"].index("--prompt-file") + 1])


def test_a_run_vibe_stopped_on_its_clock_reads_as_a_timeout(tmp_path):
    researcher = _vibe(timeout=60)
    researcher._vibe_export = tmp_path
    (tmp_path / "export.json").write_text(json.dumps({"outcome": "deadline"}), encoding="utf-8")
    with pytest.raises(TimeoutError, match="did not finish within 60s"):
        researcher._vibe_outcome(3, harness_mod.VIBE_KEYRING_BANNER + " (...)\nStopped: deadline")


def test_the_keyring_banner_is_not_a_reason_and_the_export_error_is(tmp_path):
    researcher = _vibe()
    researcher._vibe_export = tmp_path
    (tmp_path / "export.json").write_text(
        json.dumps({"outcome": "error", "error": "model refused"}), encoding="utf-8")
    code, stderr = researcher._vibe_outcome(
        2, harness_mod.VIBE_KEYRING_BANNER + " (set them as environment variables)")
    assert code == 2
    assert harness_mod.VIBE_KEYRING_BANNER not in stderr
    assert "model refused" in stderr


def test_the_export_meters_the_run(monkeypatch):
    researcher = _vibe()

    def fake_export(folder):
        return ({"usage": {"total_tokens": 7122}, "cost_usd": 0.0125}
                if folder is not None else {})

    monkeypatch.setattr(harness_mod, "_vibe_export", fake_export)
    with researcher._workspace():
        assert researcher._vibe_export is not None
        assert researcher._vibe_export.parent != Path(researcher._run_cwd)
    assert researcher.tokens_used == 7122
    assert researcher.cost_usd == pytest.approx(0.0125)
    assert researcher._vibe_export is None


# ── probes kept across restarts ──────────────────────────────────────────────


def test_a_probe_of_one_kind_does_not_freshen_another(tmp_path, monkeypatch):
    exe = tmp_path / "cli.exe"
    exe.write_text("x", encoding="utf-8")
    now = {"t": 1000.0}
    monkeypatch.setattr(cliprobe.time, "time", lambda: now["t"])
    cliprobe.record(str(exe), "models", ["a"])
    now["t"] = 5000.0
    cliprobe.record(str(exe), "help", {"text": "", "declared": []})
    assert cliprobe.entry(str(exe), "models")["at"] == 1000.0
    assert cliprobe.entry(str(exe), "help")["at"] == 5000.0


def test_codex_app_server_support_is_remembered_per_binary(tmp_path, monkeypatch):
    from app.providers.codex_transport import TransportUnavailable

    exe = tmp_path / "codex.exe"
    exe.write_text("x", encoding="utf-8")
    cliprobe.record(str(exe), "app_server", False)
    monkeypatch.setattr(harness_mod, "_CODEX_SUPPORT", {})
    monkeypatch.setattr(harness_mod, "locate", lambda _one: str(exe))
    monkeypatch.setattr(harness_mod, "_ask", lambda *_a, **_k: pytest.fail(
        "an answer persisted for this binary must not be asked again"))
    researcher = harness_mod.HarnessResearcher(row("codex"))
    researcher.transport_mode = "persistent"
    with pytest.raises(TransportUnavailable, match="no verified app-server"):
        researcher._run_codex("brief")
