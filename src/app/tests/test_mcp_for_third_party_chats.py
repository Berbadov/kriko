"""Kriko inside a chat client that is not Kriko.

The reader's words: *"Kriko MCP for third party chats."* Four things have to be
true for that to work, and each is a behaviour a client would see:

* the tools a chat client is offered each return where an answer came from,
  the page and the quote, whichever door the question came through;
* Chat's modes are one tool call away;
* a client that needs a URL gets one that answers this machine only;
* the config the Settings screen shows is one a client accepts, and the
  command in `.mcp.json` finds an engine instead of assuming a venv.
"""

import dataclasses
import functools
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import chat, chatdata, mcp_server, mcphttp
from app.tests.test_mcp_server import PACK  # one small pack, with a quoted claim
from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import ids, packstore

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(PACK["toml"]), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent(PACK["terms"]), encoding="utf-8")
    (root / "vocabulary" / "gates.yaml").write_text(textwrap.dedent(PACK["gates"]), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent(PACK["subjects"]), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(PACK["claims"]), encoding="utf-8")
    (root / "research" / "principle.md").write_text(PACK["principle"], encoding="utf-8")
    (root / "research" / "templates.yaml").write_text(PACK["templates"], encoding="utf-8")
    path = tmp_path / "knowledge.sqlite"
    monkeypatch.setattr(mcp_server, "STORE_PATH", path)
    from kriko.store.db import connect

    conn = connect(path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    return path


MAKITA = ids.subject_id("product", {"brand": "makita", "model": "DHP484"})


# ── the read tools say where an answer came from ────────────────────────


def test_lookup_returns_the_page_and_the_quote_behind_each_claim(store):
    result = mcp_server.lookup("product", {"brand": "makita", "model": "DHP484"})
    (claim,) = result["claims"]
    (source,) = claim["sources"]
    assert source["url"] == "https://example.org/report"
    assert source["quote"] == "An owner reported it."
    assert source["stance"] == "supports"


def test_get_subject_returns_the_page_and_the_quote_behind_each_claim(store):
    (claim,) = mcp_server.get_subject(MAKITA)["claims"]
    assert [(s["url"], s["quote"]) for s in claim["sources"]] == [
        ("https://example.org/report", "An owner reported it.")]


# ── chat modes as a tool ────────────────────────────────────────────────

ROWS = [{
    "url": "https://shop.example/drill", "title": "Drill", "page_read": True,
    "page_excerpt": "Makita DHP484 cordless drill, 119 EUR, in stock.",
    "source_trust": {"label": "a tool shop", "domain": "shop.example"},
}]
QUOTE = "Makita DHP484 cordless drill, 119 EUR"


@pytest.fixture
def agent(monkeypatch, store):
    """The reader's agent and the web, both scripted. Records what it was asked."""
    from app.web import tasks

    asked: list[str] = []
    searches: list[dict] = []

    def ask_about(settings, params, progress, prompt, **kwargs):
        asked.append(prompt)
        if "evidence review" in prompt:
            return json.dumps({"supported": True, "issues": [],
                               "citations": [{"url": ROWS[0]["url"], "quote": QUOTE}]}), []
        return "[Drill](https://shop.example/drill) 119 EUR", []

    original = chatdata.SOURCES["web_search"]

    @functools.wraps(original.run)
    def web(ctx, **kwargs):
        searches.append(kwargs)
        return {"rows": [dict(r) for r in ROWS], "truncated": False, "note": ""}

    monkeypatch.setattr(tasks, "_ask_about_checks", ask_about)
    monkeypatch.setattr(tasks, "_chat_web_accessors", lambda *a: (lambda q, n=5: [], lambda u: ""))
    monkeypatch.setitem(chatdata.SOURCES, "web_search", dataclasses.replace(original, run=web))
    return type("Agent", (), {"asked": asked, "searches": searches})


@pytest.mark.parametrize("mode", chat.MODES)
def test_every_chat_mode_is_a_tool_call_that_returns_its_sources_and_quotes(agent, mode):
    out = mcp_server.chat_turn("Makita DHP484", mode=mode)

    assert out["mode"] == mode
    assert agent.searches[0]["mode"] == mode  # the mode's own search, as in the window
    assert any(f"MODE: {mode.upper()}" in prompt for prompt in agent.asked)
    assert "shop.example/drill" in out["answer"]
    assert out["sources"] == [{"url": ROWS[0]["url"], "quotes": [QUOTE]}]
    assert out["quotes"] == [{"url": ROWS[0]["url"], "quote": QUOTE}]
    assert out["verification"]["claim_support"] == "supported"


def test_a_quote_the_page_does_not_contain_is_not_returned(agent, monkeypatch):
    from app.web import tasks

    def lying(settings, params, progress, prompt, **kwargs):
        if "evidence review" in prompt:
            return json.dumps({"supported": True, "issues": [], "citations": [
                {"url": ROWS[0]["url"], "quote": "Free shipping to the moon"}]}), []
        return "[Drill](https://shop.example/drill) 119 EUR", []

    monkeypatch.setattr(tasks, "_ask_about_checks", lying)
    out = mcp_server.chat_turn("Makita DHP484", mode="cheapest")
    assert out["quotes"] == []
    assert out["verification"]["claim_support"] != "supported"
    assert out["sources"] == [{"url": ROWS[0]["url"], "quotes": []}]


def test_a_chat_turn_writes_nothing_to_the_store_or_the_history(agent, store, tmp_path):
    from kriko.store.db import connect

    def count():
        conn = connect(store)
        try:
            return conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        finally:
            conn.close()

    before = count()
    mcp_server.chat_turn("Makita DHP484", mode="cheapest")
    assert count() == before
    from app.web import state

    conn = state.connect(tmp_path / "app.sqlite")
    try:
        assert conn.execute("SELECT COUNT(*) FROM chat_threads").fetchone()[0] == 0
    finally:
        conn.close()


def test_an_unknown_mode_or_an_empty_message_is_refused_before_any_agent_is_spent(agent):
    assert "mode must be one of" in mcp_server.chat_turn("Makita DHP484", mode="bargain")["error"]
    assert "empty" in mcp_server.chat_turn("   ")["error"]
    assert agent.asked == []


def test_no_agent_ready_is_an_error_that_points_at_the_free_tools(store, monkeypatch):
    from app.web import tasks

    def none_ready(*args, **kwargs):
        raise ValueError("No agent is ready.")

    monkeypatch.setattr(tasks, "_ask_about_checks", none_ready)
    monkeypatch.setattr(tasks, "_chat_web_accessors", lambda *a: (lambda q, n=5: [], lambda u: ""))
    out = mcp_server.chat_turn("Makita DHP484", mode="cheapest")
    assert "No agent is ready" in out["error"]
    assert "lookup" in out["hint"]


def test_the_chat_tool_is_among_the_tools_a_client_is_offered(store):
    assert {"chat_turn", "lookup", "get_subject", "list_subjects"} <= mcp_server.registered_tools()


# ── the local URL answers this machine and nobody else ──────────────────


def _initialise(client, **extra):
    return client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream",
                 "Content-Type": "application/json", **extra},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}})


def _served():
    """A fresh server per client: a session manager runs once per instance."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("kriko-test")
    mcphttp.configure(server, 8799)
    return server


@pytest.fixture
def http_app():
    return _served()


def test_the_url_binds_loopback_whatever_is_asked(http_app):
    assert http_app.settings.host == "127.0.0.1"
    assert http_app.settings.port == 8799
    assert mcphttp.url(8799) == "http://127.0.0.1:8799/mcp"


def test_the_url_serves_its_own_host_and_refuses_another(http_app):
    with TestClient(http_app.streamable_http_app(), base_url="http://127.0.0.1:8799") as local:
        assert _initialise(local).status_code == 200
    with TestClient(_served().streamable_http_app(), base_url="http://evil.example") as rebound:
        # A page in the reader's browser pointing a name of its own at 127.0.0.1.
        assert _initialise(rebound).status_code in (400, 403, 421)


def test_a_foreign_origin_is_refused_even_on_the_right_host(http_app):
    with TestClient(http_app.streamable_http_app(), base_url="http://127.0.0.1:8799") as client:
        assert _initialise(client, Origin="https://evil.example").status_code == 403
        assert _initialise(client, Origin="http://localhost:3000").status_code == 200


def test_a_port_that_is_taken_is_reported_not_moved(http_app, capsys):
    import socket

    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    try:
        port = held.getsockname()[1]
        assert mcphttp.serve(http_app, port) == 1
        assert "not available" in capsys.readouterr().err
    finally:
        held.close()


# ── the launcher finds an engine instead of assuming a venv ────────────


def _launcher():
    spec = importlib.util.spec_from_file_location("kriko_mcp", REPO / "tools" / "kriko_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checkout(tmp_path, venv=True):
    root = tmp_path / "checkout"
    (root / "src" / "app").mkdir(parents=True)
    if venv:
        python = root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("")
    return root


def _find(launcher, root, probe, environ=None, which=lambda name: None, executable=""):
    return launcher.find_engine(root, environ=environ or {}, platform="linux",
                                probe=probe, which=which, executable=executable)


def test_the_launcher_uses_the_venv_it_finds_and_says_where_the_source_is(tmp_path):
    launcher, root = _launcher(), _checkout(tmp_path)
    argv, env, how = _find(launcher, root, lambda py, src: True)
    assert argv == [str(root / ".venv/bin/python"), "-m", "app.sidecar"]
    assert env == {"PYTHONPATH": str(root / "src")}
    assert "venv" in how


def test_a_worktree_finds_the_main_checkouts_venv(tmp_path):
    launcher = _launcher()
    main = _checkout(tmp_path)
    (main / ".git" / "worktrees" / "w").mkdir(parents=True)
    tree = tmp_path / "worktree"
    (tree / "src" / "app").mkdir(parents=True)
    (tree / ".git").write_text(f"gitdir: {main}/.git/worktrees/w\n")
    argv, _env, how = _find(launcher, tree, lambda py, src: True)
    assert argv[0] == str(main / ".venv/bin/python")
    assert "main checkout" in how


def test_a_venv_that_cannot_import_the_engine_is_skipped_not_trusted(tmp_path):
    launcher, root = _launcher(), _checkout(tmp_path)
    argv, _env, how = _find(launcher, root, lambda py, src: py == "/usr/bin/python3",
                            executable="/usr/bin/python3")
    assert argv[0] == "/usr/bin/python3"
    assert "running this script" in how


def test_an_interpreter_the_reader_named_goes_first(tmp_path):
    launcher, root = _launcher(), _checkout(tmp_path)
    argv, _env, how = _find(launcher, root, lambda py, src: True,
                            environ={"KRIKO_PYTHON": "/opt/mine/python"})
    assert argv[0] == "/opt/mine/python" and how == "KRIKO_PYTHON"


def test_an_installed_app_is_the_engine_when_no_python_has_one(tmp_path):
    launcher, root = _launcher(), _checkout(tmp_path, venv=False)
    argv, env, how = _find(launcher, root, lambda py, src: False,
                           which=lambda name: "/opt/kriko/kriko-sidecar", executable="/usr/bin/python3")
    assert argv == ["/opt/kriko/kriko-sidecar"] and env == {}
    assert how == "an installed Kriko"


def test_no_engine_anywhere_says_what_was_tried(tmp_path):
    launcher, root = _launcher(), _checkout(tmp_path)
    with pytest.raises(LookupError) as error:
        _find(launcher, root, lambda py, src: False, executable="/usr/bin/python3")
    assert "cannot import the engine" in str(error.value)
    assert "kriko-sidecar" in str(error.value)


def test_the_repos_mcp_json_names_the_launcher_not_a_venv():
    config = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["kriko"]
    assert ".venv" not in json.dumps(server)
    assert (REPO / server["args"][0]).is_file()


def test_the_launcher_really_starts_a_server_that_lists_the_chat_tool(tmp_path):
    """Run the file `.mcp.json` names, as a client would, and ask it for its tools."""
    import subprocess

    server = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["kriko"]
    request = "\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )) + "\n"
    done = subprocess.run(
        [sys.executable, server["args"][0], "--store", str(tmp_path / "k.sqlite")],
        input=request, capture_output=True, text=True, cwd=REPO, timeout=120,
        env={**__import__("os").environ, "KRIKO_PYTHON": sys.executable})
    replies = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    listed = next(r for r in replies if r.get("id") == 2)["result"]["tools"]
    assert "chat_turn" in {t["name"] for t in listed}


# ── the Settings snippet ────────────────────────────────────────────────


def _client(tmp_path, monkeypatch):
    from app import agentconfig

    home = tmp_path / "home"
    monkeypatch.setattr(agentconfig, "_home", lambda: home)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    settings = Settings(store_path=tmp_path / "knowledge.sqlite",
                        app_state_path=tmp_path / "app.sqlite",
                        analysis_log_path=tmp_path / "analyses.jsonl")
    return TestClient(create_app(settings)), home


def test_every_client_shape_gets_a_snippet_in_its_own_key(tmp_path, monkeypatch):
    client, _home = _client(tmp_path, monkeypatch)
    body = client.get("/api/mcp-clients").json()
    rows = {c["id"]: c for c in body["clients"]}

    assert {"generic", "desktop", "ide", "vscode", "url"} <= set(rows)
    for cid in ("generic", "desktop", "ide"):
        entry = json.loads(rows[cid]["snippet"])["mcpServers"]["kriko"]
        assert entry["command"] and "--mcp" in entry["args"]
        assert str(tmp_path / "knowledge.sqlite") in entry["args"]  # the store this window reads
    assert "kriko" in json.loads(rows["vscode"]["snippet"])["servers"]
    assert json.loads(rows["url"]["snippet"])["mcpServers"]["kriko"] == {"url": mcphttp.url()}
    assert "--mcp-http" in rows["url"]["start"]
    assert body["url"].startswith("http://127.0.0.1:")


def test_writing_a_client_merges_one_key_and_keeps_the_readers_other_servers(tmp_path, monkeypatch):
    client, home = _client(tmp_path, monkeypatch)
    config = home / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))

    done = client.post("/api/mcp-clients/ide/write").json()

    assert done["state"] == "connected" and done["id"] == "ide"
    written = json.loads(config.read_text())
    assert written["mcpServers"]["other"] == {"command": "x"} and written["theme"] == "dark"
    assert written["mcpServers"]["kriko"] == json.loads(
        {c["id"]: c for c in client.get("/api/mcp-clients").json()["clients"]}["ide"]["snippet"]
    )["mcpServers"]["kriko"]


def test_the_editor_chat_is_written_under_servers_not_mcpservers(tmp_path, monkeypatch):
    client, _home = _client(tmp_path, monkeypatch)
    row = {c["id"]: c for c in client.get("/api/mcp-clients").json()["clients"]}["vscode"]
    assert client.post("/api/mcp-clients/vscode/write").json()["state"] == "connected"
    assert "kriko" in json.loads(Path(row["path"]).read_text())["servers"]


def test_a_shown_only_shape_has_nowhere_to_be_written(tmp_path, monkeypatch):
    client, _home = _client(tmp_path, monkeypatch)
    for cid in ("generic", "url", "emacs"):
        assert client.post(f"/api/mcp-clients/{cid}/write").status_code == 404


def test_a_config_the_reader_broke_is_refused_and_left_alone(tmp_path, monkeypatch):
    client, home = _client(tmp_path, monkeypatch)
    config = home / ".cursor" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text("{ not json")

    assert client.post("/api/mcp-clients/ide/write").status_code == 409
    assert config.read_text() == "{ not json"
    row = {c["id"]: c for c in client.get("/api/mcp-clients").json()["clients"]}["ide"]
    assert row["state"] == "unreadable" and row["writable"] is False
