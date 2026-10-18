"""The Agents screen's marketplace: what this machine can run, one row each.

The reader's words: "Local agent must be in agents tab with its marketplace."
A market row is an agent as the reader meets it — a coding-agent CLI, the model
on this machine, or an API they hold a key for — carrying what this
installation knows about it and the one action left to take. Every fact in it
is one the engine already had: these tests pin that the row is *composed* from
those answers rather than invented beside them, and that the composition is the
same one `/api/prefs` serves.
"""

from fastapi.testclient import TestClient

from app import agentconfig, prefs
from app.providers import apiagent
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )


def _client(tmp_path):
    return TestClient(create_app(_settings(tmp_path)))


def _redirect_roots(monkeypatch, home):
    """Point every root `agentconfig` reads at a throwaway directory.

    The same three roots `test_agent_config` redirects, for the same reason: a
    test that reads the author's own `~/.claude.json` reports *their* machine,
    and one that writes it edits it.
    """
    monkeypatch.setattr(agentconfig, "_home", lambda: home)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))


def _rows(client, monkeypatch, *, harnesses=(), unusable=(), missing=(), api=((), ())):
    """The market as its rows, over the engine answers a test supplies."""
    ready, keyless = api
    monkeypatch.setattr(prefs, "choices", lambda conn, *a, **k: {
        "chosen": {prefs.HARNESS: "codex"},
        "harnesses": list(harnesses),
        "unusable": list(unusable),
        "missing": list(missing),
    })
    monkeypatch.setattr(
        prefs, "api_agent_rows", lambda conn: (list(ready), list(keyless)))
    body = client.get("/api/agent-market").json()
    return {row["id"]: row for row in body["agents"]}


def test_a_cli_that_is_here_but_not_wired_is_offered_connect(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    market = _rows(_client(tmp_path), monkeypatch, harnesses=[
        {"id": "claude-code", "label": "Claude Code",
         "path": str(tmp_path / "bin" / "claude.exe")},
    ])

    row = market["claude-code"]
    assert (row["state"], row["kind"]) == ("ready", "cli")
    assert row["action"] == "connect"
    assert row["where"].endswith("claude.exe"), "how it was found belongs on the row"
    assert row["wiring"] == "absent"


def test_the_same_cli_is_offered_use_once_its_config_carries_this_store(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    client = _client(tmp_path)
    client.post("/api/agent-targets/claude-code/connect")

    market = _rows(client, monkeypatch, harnesses=[
        {"id": "claude-code", "label": "Claude Code", "path": "C:/x/claude.exe"},
    ])

    assert market["claude-code"]["wiring"] == "connected"
    assert market["claude-code"]["action"] == "use"


def test_an_agent_that_answers_somewhere_else_never_offers_use(tmp_path, monkeypatch):
    """Cursor answers in its own window, so the only thing Kriko can do for it
    is write its config — and a connected Cursor still offers Connect."""
    _redirect_roots(monkeypatch, tmp_path / "home")
    client = _client(tmp_path)
    client.post("/api/agent-targets/cursor/connect")

    market = _rows(client, monkeypatch)

    assert market["cursor"]["state"] == "ready"
    assert market["cursor"]["wiring"] == "connected"
    assert market["cursor"]["action"] == "connect"


def test_an_agent_this_build_will_not_drive_is_not_offered_use(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    market = _rows(_client(tmp_path), monkeypatch, unusable=[
        {"id": "gemini-cli", "label": "Gemini CLI",
         "why": "not yet verified against the real CLI"},
    ])

    row = market["gemini-cli"]
    assert row["state"] == "needs_setup"
    assert row["action"] == "setup"
    assert "verified" in row["detail"], "the engine's own reason is what it shows"


def test_a_cli_that_is_not_installed_is_offered_install(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    market = _rows(_client(tmp_path), monkeypatch, missing=[{
        "id": "codex", "label": "Codex", "command": "codex",
        "download_url": "https://example.test/codex",
        "install_hint": "npm install -g @openai/codex",
        "needs_account": "a ChatGPT plan", "can_install": True,
    }])

    row = market["codex"]
    assert (row["state"], row["action"]) == ("not_installed", "install")
    assert row["where"] == "codex", "a missing CLI names the command that was looked for"
    assert row["detail"] == "npm install -g @openai/codex"
    assert row["can_install"] is True


def test_a_cli_with_no_install_of_its_own_is_offered_set_up(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    market = _rows(_client(tmp_path), monkeypatch, missing=[{
        "id": "something", "label": "Something", "command": "something",
        "download_url": "https://example.test/get",
        "install_hint": "download it from the vendor", "needs_account": "",
        "can_install": False,
    }])

    row = market["something"]
    assert row["action"] == "setup"
    assert row["url"] == "https://example.test/get"


def test_an_api_agent_without_a_key_is_offered_set_up(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    market = _rows(_client(tmp_path), monkeypatch, api=((), ({
        "id": "mistral-api", "label": "Mistral API",
        "download_url": "https://example.test/keys",
        "install_hint": "save a key for it in Settings",
        "needs_account": "Bills your key, per token and per search",
        "cost_basis": "per_token",
    },)))

    row = market["mistral-api"]
    assert row["state"] == "not_installed"
    assert row["action"] == "setup"
    assert row["kind"] == "api", "a keyed agent is not a CLI on PATH"
    assert row["url"] == "https://example.test/keys"


def test_a_keyless_api_agent_row_says_what_it_is(tmp_path, monkeypatch):
    """`_kind` reads the engine's own flag, so the *missing* row a keyless API
    agent gets has to carry it: the market never guesses a kind."""
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        monkeypatch.setattr(apiagent, "available", lambda: [])
        _ready, keyless = prefs.api_agent_rows(conn)
    finally:
        conn.close()

    assert keyless, "an unkeyed agent must still be offered"
    assert {row["cost_basis"] for row in keyless} == {"per_token"}
    assert {row["id"] for row in keyless} == {one.id for one in apiagent.KNOWN}


def test_the_market_is_composed_from_the_engine_s_own_lists(tmp_path, monkeypatch):
    """The real composition, on whatever machine runs the suite: every row the
    preference screen knows — and the local agent it appends — is a row here,
    and a config Kriko can write is one too."""
    _redirect_roots(monkeypatch, tmp_path / "home")
    client = _client(tmp_path)
    market = {row["id"] for row in client.get("/api/agent-market").json()["agents"]}
    engine = client.get("/api/prefs").json()

    assert market >= {row["id"] for row in engine["harnesses"]}
    assert market >= {row["id"] for row in engine["unusable"]}
    assert market >= {row["id"] for row in engine["missing"]}
    assert market >= {"local"}, "the model on this machine is an agent here too"
    assert market >= {t["id"] for t in client.get("/api/agent-targets").json()["targets"]}


def test_every_row_offers_one_of_the_four_actions(tmp_path, monkeypatch):
    _redirect_roots(monkeypatch, tmp_path / "home")
    client = _client(tmp_path)
    body = client.get("/api/agent-market").json()

    assert body["agents"], "an empty machine still has agents to install"
    for row in body["agents"]:
        assert row["action"] in {"use", "connect", "install", "setup"}, row
        assert row["state"] in {"ready", "needs_setup", "not_installed"}, row
        assert row["kind"] in {"cli", "local", "api"}, row
        assert row["id"] and row["label"], row
