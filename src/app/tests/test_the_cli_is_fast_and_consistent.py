"""The CLI rebuilt for speed and one output contract.

Two properties are pinned here, both mechanical so they cannot drift:

1. **Fast.** Importing `app.cli` must not pull in the engine, the web app or
   the bench tree — `kriko --version` used to pay for `app.agentbench`'s
   multi-second import because the parser imported it while being built. A
   subprocess asserts on `sys.modules`, so an import added anywhere in the
   chain fails here, not in a stopwatch somebody has to believe.
2. **Consistent.** Every command answers `--json` with one JSON document on
   stdout, and the read-only app-state commands (`costs`, `operations`,
   `sites list`, `verify --list`, `drafts`, `prefs`) answer from `app.sqlite`
   beside `--store` directly — no engine is attached to or started, the answer
   does not depend on one running, and no `app.sqlite` is created just to say
   "nothing yet". The write half still goes to an engine (pinned in
   test_cli.py's `--no-start` test).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import cli
from app.tests.test_cli import DRILLISH, _pack

REPO = Path(__file__).resolve().parents[3]


def _run_module(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_importing_the_cli_pulls_in_no_engine_no_web_no_bench():
    done = _run_module(
        "import sys, app.cli\n"
        "heavy = [m for m in ('kriko', 'app.web', 'app.agentbench', 'app.tui',"
        " 'fastapi', 'uvicorn') if m in sys.modules]\n"
        "print(','.join(heavy))\n"
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "", f"app.cli import pulled in: {done.stdout}"


def test_version_answers_in_well_under_a_second_of_imports():
    """The bound is deliberately loose — this pins the *shape* (interpreter +
    argparse only), not a stopwatch; the sys.modules test above pins the cause."""
    import time

    started = time.monotonic()
    done = _run_module("import app.cli; print(app.cli._version())")
    elapsed = time.monotonic() - started
    assert done.returncode == 0, done.stderr
    assert elapsed < 2.0, f"importing app.cli took {elapsed:.2f}s"


def test_building_the_parser_for_another_command_skips_the_bench_tree():
    done = _run_module(
        "import sys\n"
        "from app import cli\n"
        "cli.build_parser('packs')\n"
        "assert 'app.agentbench' not in sys.modules, 'parser build imported the bench'\n"
        "print('ok')\n"
    )
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_agent_bench_still_gets_its_arguments_when_it_is_the_command():
    done = subprocess.run(
        [sys.executable, "-m", "app.cli", "agent-bench", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert done.returncode == 0, done.stderr
    assert "--profile" in done.stdout


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "store.sqlite")


def _json_out(capsys, *argv) -> dict:
    assert cli.main(list(argv)) == 0
    return json.loads(capsys.readouterr().out)


def test_every_command_answers_json_with_stable_keys(store_path, capsys, tmp_path):
    packs = _json_out(capsys, "--store", store_path, "packs", "--json")
    assert packs == {"packs": []}

    looked = _json_out(capsys, "--store", store_path, "--json", "lookup",
                       "brand=x", "model=y")
    assert set(looked) == {"match", "coverage", "claims"}
    assert looked["claims"] == []
    assert looked["match"]["method"] == "no_match"

    costs = _json_out(capsys, "--store", store_path, "costs", "--json")
    assert costs["spent"]["usd"] == 0 and costs["spent"]["runs"] == 0
    assert "estimates" in costs and "keys" in costs and "balance" in costs

    ops = _json_out(capsys, "--store", store_path, "operations", "--json")
    assert ops == {"items": [], "running": 0, "last_id": 0}

    sites = _json_out(capsys, "--store", store_path, "sites", "--json")
    assert sites == {"registered": [], "requested": []}

    verify = _json_out(capsys, "--store", store_path, "verify", "--list", "--json")
    assert "items" in verify and "counts" in verify

    drafts = _json_out(capsys, "--store", store_path, "drafts", "--json")
    assert drafts == {"items": []}

    prefs = _json_out(capsys, "--store", store_path, "prefs", "--json")
    assert "chosen" in prefs and "harnesses" in prefs


def test_lookup_json_carries_the_claims(store_path, capsys, tmp_path):
    pack = _pack(tmp_path, "tools", DRILLISH)
    assert cli.main(["--store", store_path, "install", str(pack)]) == 0
    capsys.readouterr()
    result = _json_out(capsys, "--store", store_path, "lookup", "--json",
                       "brand=makita", "model=DHP484", "--ctx", "usage_hours=800")
    assert result["match"]["method"] == "exact"
    assert len(result["claims"]) == 1
    claim = result["claims"][0]
    assert claim["title"] == "Chuck slips under torque"
    assert claim["severity"] == "high"
    assert claim["sources"][0]["url"] == "https://example.org/report"

    packs = _json_out(capsys, "--store", store_path, "packs", "--json")
    assert [p["pack_id"] for p in packs["packs"]] == ["tools"]
    assert packs["packs"][0]["enabled"] is True


def test_read_commands_need_no_engine_and_create_no_app_state(store_path, tmp_path, capsys):
    """The consistency guarantee: the answer comes from the files beside
    `--store` in this process. No engine is running in the test environment,
    none is started, and a machine whose app never ran gets "nothing yet"
    without an `app.sqlite` appearing."""
    for command in (["costs"], ["operations"], ["sites"], ["verify", "--list"],
                    ["drafts"], ["prefs"]):
        assert cli.main(["--store", store_path, *command]) == 0
        capsys.readouterr()
    assert not (tmp_path / "app.sqlite").exists()


def test_read_commands_do_not_open_an_engine_port(store_path, capsys, monkeypatch):
    """If a read command tried to attach or start an engine, this fails: the
    client's `connect` raises if it is reached at all."""
    from app.tui import client as tui_client

    def _boom(*args, **kwargs):
        raise AssertionError("a read-only command tried to reach an engine")

    monkeypatch.setattr(tui_client, "connect", _boom)
    monkeypatch.setattr(tui_client, "serve_in_thread", _boom)
    for command in (["costs"], ["operations"], ["sites", "list"],
                    ["verify", "--list"], ["drafts"], ["prefs"]):
        assert cli.main(["--store", store_path, *command]) == 0
        capsys.readouterr()


def test_errors_are_one_line_on_stderr_with_the_kriko_prefix(store_path, capsys):
    assert cli.main(["--store", store_path, "uninstall", "nope"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("kriko: ")
    assert "Traceback" not in captured.err
