"""Writing into someone else's config file.

Every test here is about damage rather than features: the module's whole job is
to add one key to a file it did not author, and the ways that goes wrong —
clobbering a reader's other servers, half-writing a file, calling a connection
good when it points at the wrong store — are all silent.
"""

import json
import sys
from pathlib import Path

import pytest

from app import agentconfig


@pytest.fixture
def target(tmp_path):
    return agentconfig.Target("t", "Test harness", tmp_path / "mcp.json")


SERVER = {"type": "stdio", "command": "/usr/bin/kriko", "args": ["--mcp", "--store", "/s/k.sqlite"]}


def read(target):
    return json.loads(target.path.read_text(encoding="utf-8"))


# ── status ──────────────────────────────────────────────────────────────

def test_a_harness_that_was_never_configured_is_absent_not_an_error(target):
    row = agentconfig.status_of(target, server_name="kriko", store_path="/s/k.sqlite")
    assert row["state"] == "absent"
    assert row["exists"] is False


def test_an_entry_naming_this_store_reads_as_connected(target):
    target.path.write_text(json.dumps({"mcpServers": {"kriko": SERVER}}), encoding="utf-8")
    row = agentconfig.status_of(target, server_name="kriko", store_path="/s/k.sqlite")
    assert row["state"] == "connected"


def test_an_entry_naming_a_different_store_is_stale_not_connected(target):
    """The failure that looks exactly like success.

    An agent wired to the wrong `knowledge.sqlite` runs, answers, and writes
    findings into a store this window never reads. Reporting it as connected
    would leave the reader with nothing to notice.
    """
    target.path.write_text(json.dumps({"mcpServers": {"kriko": SERVER}}), encoding="utf-8")
    row = agentconfig.status_of(target, server_name="kriko", store_path="/other/k.sqlite")
    assert row["state"] == "stale"


def test_a_config_someone_broke_by_hand_is_reported_not_raised(target):
    target.path.write_text("{ this is not json", encoding="utf-8")
    row = agentconfig.status_of(target, server_name="kriko", store_path="/s/k.sqlite")
    assert row["state"] == "unreadable"
    assert "JSON" in row["detail"]


def test_the_harness_a_reader_uses_is_not_hidden_by_one_they_do_not(tmp_path, monkeypatch):
    """One bad config must not cost the reader the other three rows."""
    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path)
    (tmp_path / ".claude.json").write_text("nonsense{", encoding="utf-8")
    rows = [
        agentconfig.status_of(t, server_name="kriko", store_path="/s/k.sqlite")
        for t in agentconfig.targets()
    ]
    assert len(rows) >= 3
    assert {r["state"] for r in rows} >= {"unreadable", "absent"}


# ── connecting ──────────────────────────────────────────────────────────

def test_connecting_creates_the_file_when_the_harness_has_no_config_yet(target):
    agentconfig.connect(target, server_name="kriko", server=SERVER)
    assert read(target)["mcpServers"]["kriko"] == SERVER


def test_connecting_leaves_every_other_server_and_setting_untouched(target):
    target.path.write_text(json.dumps({
        "mcpServers": {"other": {"command": "keep-me"}},
        "theme": "dark",
        "apiKeyHelper": "~/.secrets/get",
    }), encoding="utf-8")
    agentconfig.connect(target, server_name="kriko", server=SERVER)

    config = read(target)
    assert config["mcpServers"]["other"] == {"command": "keep-me"}
    assert config["theme"] == "dark"
    assert config["apiKeyHelper"] == "~/.secrets/get"


def test_connecting_twice_replaces_rather_than_duplicates(target):
    agentconfig.connect(target, server_name="kriko", server={"command": "old"})
    agentconfig.connect(target, server_name="kriko", server=SERVER)
    assert read(target)["mcpServers"] == {"kriko": SERVER}


def test_vs_code_gets_the_key_it_actually_reads(tmp_path):
    """`servers`, not `mcpServers`. A config under the wrong key is ignored in
    silence — the harness starts fine and simply has no Kriko."""
    vscode = agentconfig.Target("vscode", "VS Code", tmp_path / "mcp.json", key="servers")
    agentconfig.connect(vscode, server_name="kriko", server=SERVER)
    assert "servers" in read(vscode)
    assert "mcpServers" not in read(vscode)


def test_a_config_that_cannot_be_parsed_is_refused_rather_than_overwritten(target):
    """Their file, their contents. Replacing what we cannot read is the one
    outcome worse than not connecting."""
    target.path.write_text('{"mcpServers": {"other": ', encoding="utf-8")
    with pytest.raises(ValueError):
        agentconfig.connect(target, server_name="kriko", server=SERVER)
    assert target.path.read_text(encoding="utf-8") == '{"mcpServers": {"other": '


def test_no_temp_file_survives_a_successful_write(target):
    agentconfig.connect(target, server_name="kriko", server=SERVER)
    assert [p.name for p in target.path.parent.iterdir()] == ["mcp.json"]


# ── the environment a config carries for itself (B131) ─────────────────────

def test_off_windows_the_platform_env_is_empty():
    assert agentconfig.platform_env("linux", {"SystemRoot": "C:\\Windows"}) == {}


def test_on_windows_the_process_cannot_start_without_vars_are_carried():
    env = agentconfig.platform_env("win32", {
        "SystemRoot": "C:\\Windows", "TEMP": "C:\\Users\\r\\AppData\\Local\\Temp",
        "TMP": "C:\\Users\\r\\AppData\\Local\\Temp", "PATH": "C:\\Windows\\System32",
        "UNRELATED": "keep-out",
    })
    assert env["SystemRoot"] == "C:\\Windows"
    assert env["TEMP"] and env["PATH"]
    assert "UNRELATED" not in env


def test_platform_env_never_writes_a_key_the_environment_did_not_have():
    """A missing `SystemRoot` must not become the literal string `None` in a
    harness config — that is worse than omitting the key."""
    env = agentconfig.platform_env("win32", {})
    assert env == {}


# ── redirecting HOME must also redirect Claude Desktop's path (research-1) ──


def test_a_redirected_home_redirects_claude_desktop_too(tmp_path, monkeypatch):
    """A HOME-redirected test run must never resolve to the real %APPDATA%.

    Before this fix, `_appdata()` trusted an inherited `APPDATA` env var
    unconditionally, so a caller that redirects `HOME`/`USERPROFILE` alone (as
    every one-click test does) still got the operator's
    real roaming folder back for Claude Desktop specifically — the one target
    out of four whose isolation that left broken.
    """
    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path)
    monkeypatch.setenv("APPDATA", str(Path("C:/Users/someone-else/AppData/Roaming")))
    monkeypatch.setattr(sys, "platform", "win32")
    base = agentconfig._appdata()
    assert base is not None
    assert tmp_path in base.parents or base == tmp_path / "AppData" / "Roaming"


def test_a_real_appdata_under_the_real_home_is_still_honoured(tmp_path, monkeypatch):
    """The fix must not break the ordinary, non-redirected case.

    On a real machine `%APPDATA%` sits under the real home, and that value —
    not a recomputed one — is still what gets used.
    """
    monkeypatch.setattr(agentconfig, "_home", lambda: tmp_path)
    real_appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(real_appdata))
    monkeypatch.setattr(sys, "platform", "win32")
    assert agentconfig._appdata() == real_appdata
