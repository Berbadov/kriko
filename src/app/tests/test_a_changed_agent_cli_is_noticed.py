"""A coding-agent CLI that ships a new version is noticed, and checked.

The reader's ask: "Vibe code CLI gets an update that would make our app
functionality diminish — we must act fast and adapt our app." `cliprobe`
already re-reads a changed binary's `--help`; nothing said that it changed,
or that a flag Kriko passes was gone. `app.cliwatch` says both: on
`/api/health`, on each harness row, and from `tools/cli_watch.py` with an
exit status a scheduled task can act on.
"""

import importlib.util
import logging
from pathlib import Path

import pytest

from app import cliwatch
from app.providers import harness

EXE = "C:/tools/fake-vibe.exe"

VIBE = next(h for h in harness.KNOWN if h.id == "mistral-vibe")
CODEX = next(h for h in harness.KNOWN if h.id == "codex")

VIBE_HELP = """usage: vibe [options]
  --output <OUTPUT>  [possible values: text, json, streaming]
  --agent <NAME>     e.g. default, plan, auto-approve
  --trust
  --enabled-tools <TOOL>
  --prompt <TEXT>
  --max-price <USD>
  --max-turns <N>
"""


def _cli(monkeypatch, *, help_text: str, version: str):
    for name in ("_HELP", "_DECLARED", "_HELP_FAILED", "_HELP_STAMP"):
        monkeypatch.setattr(harness, name, {})
    monkeypatch.setattr(harness, "locate", lambda one: EXE)

    def ask(executable, *argv, **_):
        if argv == ("--version",):
            return f"vibe {version}\n"
        return help_text

    monkeypatch.setattr(harness, "_ask", ask)


def test_the_contract_is_read_off_the_harness_row():
    vibe = cliwatch.contract_for(VIBE)
    assert {"--output", "--agent", "--trust", "--enabled-tools", "--prompt"} <= set(vibe.must)
    assert {"--max-price", "--max-turns"} <= set(vibe.should)
    assert ("--output", "streaming") in vibe.values
    # Codex's flags are its `exec` subcommand's, and half of them are added
    # by `command_for` rather than listed in `args`.
    codex = cliwatch.contract_for(CODEX)
    assert codex.help_argv == ("exec", "--help")
    assert {"--json", "--sandbox", "--ignore-user-config", "--ignore-rules"} <= set(codex.must)


def test_an_unchanged_cli_needs_no_attention(monkeypatch):
    _cli(monkeypatch, help_text=VIBE_HELP, version="3.1.0")
    base = {"mistral-vibe": {"version": "3.1.0", "declared": cliwatch.check(VIBE, {})["declared"]}}
    row = cliwatch.check(VIBE, base)
    assert row["state"] == "ok"
    assert not cliwatch.needs_attention(row)


def test_a_new_version_is_a_change_even_when_every_flag_is_still_there(monkeypatch):
    _cli(monkeypatch, help_text=VIBE_HELP, version="3.2.0")
    row = cliwatch.check(VIBE, {"mistral-vibe": {"version": "3.1.0"}})
    assert row["state"] == "ok" and row["changed"]
    assert "3.1.0 -> 3.2.0" in cliwatch.summary(row)


def test_a_renamed_required_flag_breaks_the_contract(monkeypatch):
    _cli(monkeypatch, help_text=VIBE_HELP.replace("--output <OUTPUT>", "--format <F>"),
         version="4.0.0")
    previous = {"version": "3.1.0", "declared": ["--output", "--agent", "--trust"]}
    row = cliwatch.check(VIBE, {"mistral-vibe": previous})
    assert row["state"] == "broken"
    assert row["missing_must"] == ["--output"]
    assert row["lost"] == ["--output"]
    assert "missing required --output" in cliwatch.summary(row)


def test_a_lost_optional_flag_or_format_value_is_degraded_not_broken(monkeypatch):
    text = VIBE_HELP.replace("  --max-turns <N>\n", "").replace("streaming", "ndjson")
    _cli(monkeypatch, help_text=text, version="3.1.0")
    row = cliwatch.check(VIBE, {})
    assert row["state"] == "degraded"
    assert row["missing_should"] == ["--max-turns"]
    assert "--output streaming" in row["missing_values"]


def test_a_cli_that_says_nothing_is_unknown_not_broken(monkeypatch):
    _cli(monkeypatch, help_text="", version="3.1.0")
    row = cliwatch.check(VIBE, {"mistral-vibe": {"version": "3.1.0", "declared": ["--output"]}})
    assert row["state"] == "unknown" and row["lost"] == []


def test_accepting_records_only_what_is_not_broken():
    rows = [
        {"id": "a", "installed": True, "state": "ok", "version": "1.0", "declared": ["--x"]},
        {"id": "b", "installed": True, "state": "broken", "version": "2.0", "declared": []},
        {"id": "c", "installed": False, "state": "absent", "version": "", "declared": []},
    ]
    out = cliwatch.accepted(rows, {"b": {"version": "1.9"}}, today="2026-11-08")
    assert out["a"] == {"version": "1.0", "declared": ["--x"], "checked": "2026-11-08"}
    assert out["b"] == {"version": "1.9"}
    assert "c" not in out


def test_the_baseline_round_trips(tmp_path):
    path = tmp_path / "cli_versions.json"
    cliwatch.save_baseline({"x": {"version": "1"}}, path)
    assert cliwatch.load_baseline(path) == {"x": {"version": "1"}}
    assert cliwatch.load_baseline(tmp_path / "missing.json") == {}


def test_the_registry_is_read_off_the_install_line():
    assert cliwatch.registry_for(CODEX) == ("npm", "@openai/codex")
    assert cliwatch.registry_for(VIBE) == ("pypi", "mistral-vibe")
    claude = next(h for h in harness.KNOWN if h.id == "claude-code")
    assert cliwatch.registry_for(claude) == ("npm", "@anthropic-ai/claude-code")


def test_the_latest_published_version_is_asked_of_that_registry():
    asked = []

    def fetch(url, timeout):
        asked.append(url)
        return {"info": {"version": "3.2.0"}} if "pypi" in url else {"version": "0.170.0"}

    assert cliwatch.latest_published(VIBE, fetch=fetch) == "3.2.0"
    assert cliwatch.latest_published(CODEX, fetch=fetch) == "0.170.0"
    assert asked == ["https://pypi.org/pypi/mistral-vibe/json",
                     "https://registry.npmjs.org/@openai/codex/latest"]

    def offline(url, timeout):
        raise OSError("no network")

    assert cliwatch.latest_published(VIBE, fetch=offline) == ""


def test_the_engine_warns_once_and_serves_the_drift(monkeypatch, caplog):
    _cli(monkeypatch, help_text=VIBE_HELP, version="3.2.0")
    monkeypatch.setattr(cliwatch, "load_baseline", lambda path=None: {"mistral-vibe": {"version": "3.1.0"}})
    started = []
    monkeypatch.setattr(cliwatch, "_spawn", lambda one, stamp: started.append(one.id))

    assert cliwatch.status(VIBE) is None, "the first read never waits on a probe"
    assert started == ["mistral-vibe"]

    with caplog.at_level(logging.WARNING, logger="app.cliwatch"):
        cliwatch._run_check(VIBE)
        cliwatch._run_check(VIBE)
    warnings = [r for r in caplog.records if "agent CLI drift" in r.getMessage()]
    assert len(warnings) == 1
    assert "3.1.0 -> 3.2.0" in warnings[0].getMessage()

    shown = cliwatch.status(VIBE)
    assert shown is not None and shown["attention"] and shown["version"] == "3.2.0"
    assert [d["id"] for d in cliwatch.drift()] == ["mistral-vibe"]

    from app.web.app import _cli_drift

    assert _cli_drift()[0]["known_good"] == "3.1.0"


def _tool():
    path = Path(__file__).resolve().parents[3] / "tools" / "cli_watch.py"
    spec = importlib.util.spec_from_file_location("cli_watch_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version,help_text,code", [
    ("3.1.0", VIBE_HELP, 0),
    ("3.2.0", VIBE_HELP, 1),
    ("4.0.0", VIBE_HELP.replace("--trust", "--trusted"), 2),
])
def test_the_tool_exits_non_zero_on_a_change_or_a_break(monkeypatch, tmp_path, capsys,
                                                         version, help_text, code):
    _cli(monkeypatch, help_text=help_text, version=version)
    baseline = tmp_path / "cli_versions.json"
    declared = cliwatch.check(VIBE, {})["declared"]
    _cli(monkeypatch, help_text=help_text, version=version)
    cliwatch.save_baseline({"mistral-vibe": {"version": "3.1.0", "declared": declared}}, baseline)
    monkeypatch.setattr(harness, "KNOWN", (VIBE,))

    assert _tool().main(["--offline", "--baseline", str(baseline)]) == code
    out = capsys.readouterr().out
    if code == 1:
        assert "~ version: 3.1.0 -> 3.2.0" in out
    if code == 2:
        assert "required flag gone: --trust" in out


def test_the_tool_accepts_a_passing_cli_as_last_known_good(monkeypatch, tmp_path):
    _cli(monkeypatch, help_text=VIBE_HELP, version="3.2.0")
    baseline = tmp_path / "cli_versions.json"
    cliwatch.save_baseline({"mistral-vibe": {"version": "3.1.0"}}, baseline)
    monkeypatch.setattr(harness, "KNOWN", (VIBE,))
    tool = _tool()

    assert tool.main(["--offline", "--accept", "--baseline", str(baseline)]) == 0
    assert cliwatch.load_baseline(baseline)["mistral-vibe"]["version"] == "3.2.0"
    assert tool.main(["--offline", "--baseline", str(baseline)]) == 0


def test_the_shipped_baseline_names_only_known_clis():
    known = {h.id for h in harness.KNOWN}
    for cli_id, row in cliwatch.load_baseline().items():
        assert cli_id in known
        assert row.get("version")
