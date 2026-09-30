"""B155: Claude Code reads the pages that sites refuse it.

    do we know why claude code web search stopped working suddenly?
    ... you reckon no solution to this?

Sites behind Cloudflare's AI-bot blocking answer Claude Code's fetcher
(`Claude-User`) with a 403 (the reader's quick look on a laptop: "Three of my
page fetches returned 403 errors, which used up my three page opens"). Kriko
never changes the agent a CLI fetches with, so the answer is a second way to
read the page: Exa's free hosted MCP server, handed to any CLI that takes a
per-run MCP config, next to the search and fetch tools it already has.

None of these tests starts a real agent. A few start a Python stand-in that
reports what it was given.
"""

import json
import sys
from pathlib import Path

import pytest

from app import quicklook
from app.providers import harness as harness_mod
from app.providers.harness import Harness, HarnessResearcher, PageReader
from kriko.research.agent import REFUSED_PAGE

READER_TOOL = "mcp__exa__web_fetch_exa"

#: What `claude --help` declares on this build, trimmed to what the vector reads.
DECLARED = frozenset({
    "--output-format", "--verbose", "--allowedTools", "--strict-mcp-config",
    "--safe-mode", "--mcp-config", "--model", "--effort",
})


def _claude() -> Harness:
    return next(h for h in harness_mod.KNOWN if h.id == "claude-code")


def _declares(monkeypatch, flags=DECLARED, path="/usr/bin/claude"):
    monkeypatch.setattr(harness_mod, "locate", lambda one: path)
    monkeypatch.setattr(harness_mod, "declared", lambda _: frozenset(flags))
    monkeypatch.setattr(harness_mod, "helptext", lambda _: "stream-json")


# ── the command line ─────────────────────────────────────────────────────────


def test_a_reader_config_reaches_the_command_line_with_its_tool_allowed(monkeypatch):
    _declares(monkeypatch)
    vector = harness_mod.command_for(_claude(), reader_config="/run/reader.json")
    assert vector[vector.index("--mcp-config") + 1] == "/run/reader.json"
    grant = vector[vector.index("--allowedTools") + 1]
    assert grant == f"WebSearch,WebFetch,{READER_TOOL}"
    # Still the sandbox it was: no config of the reader's own gets in beside it.
    assert "--strict-mcp-config" in vector and "--safe-mode" in vector


def test_the_grant_is_search_fetch_and_the_readers_fetch_and_nothing_else(monkeypatch):
    """An allowlist checked by name. The reader's search tool is deliberately
    absent: search was never refused, and a second search tool would only give
    the agent a second place to spend its budget."""
    _declares(monkeypatch)
    vector = harness_mod.command_for(_claude(), reader_config="/run/reader.json")
    tools = vector[vector.index("--allowedTools") + 1].split(",")
    assert tools == [*harness_mod.SEARCH_TOOLS, READER_TOOL]
    assert not any("search_exa" in tool for tool in tools)


def test_the_plain_vector_gets_the_reader_too(monkeypatch):
    """A build that cannot stream still runs, and still reads refused pages."""
    _declares(monkeypatch)
    monkeypatch.setattr(harness_mod, "helptext", lambda _: "choices: json")
    vector = harness_mod.command_for(_claude(), reader_config="/run/reader.json")
    assert "stream-json" not in vector
    assert vector[vector.index("--allowedTools") + 1].endswith(READER_TOOL)
    assert "--mcp-config" in vector


def test_the_reader_is_left_out_where_the_cli_does_not_declare_the_flag(monkeypatch):
    """Feature detection, as B154 did it: an older build keeps the plane and
    loses the reader, never the other way round."""
    _declares(monkeypatch, DECLARED - {"--mcp-config"})
    vector = harness_mod.command_for(_claude(), reader_config="/run/reader.json")
    assert "--mcp-config" not in vector and "/run/reader.json" not in vector
    assert vector[vector.index("--allowedTools") + 1] == ",".join(harness_mod.SEARCH_TOOLS)


def test_no_config_means_no_reader_flags(monkeypatch):
    _declares(monkeypatch)
    vector = harness_mod.command_for(_claude())
    assert "--mcp-config" not in vector
    assert vector[vector.index("--allowedTools") + 1] == ",".join(harness_mod.SEARCH_TOOLS)


def test_a_row_that_declares_no_reader_never_gets_one(monkeypatch):
    """The reader is a row's own declaration, not a list of CLI names here: a
    CLI whose row carries no `reader` gets the same vector with or without a
    config, whatever its `--help` says."""
    _declares(monkeypatch)
    bare = Harness("bare", "Bare", "bare", ("--allowedTools", "WebFetch"))
    assert bare.reader is None
    assert harness_mod.command_for(bare, reader_config="/run/reader.json") == (
        harness_mod.command_for(bare))


def test_a_reader_without_an_allowlist_to_extend_is_not_attached(monkeypatch):
    """A config with no grant would make every read a permission prompt that a
    headless run auto-denies. Better none than that."""
    _declares(monkeypatch)
    odd = Harness("odd", "Odd", "odd", ("-p",),
                  reader=PageReader("--mcp-config", "--allowedTools", "mcp__{server}__{tool}"))
    assert harness_mod.command_for(odd, reader_config="/run/reader.json") == (
        harness_mod.command_for(odd))


def test_every_row_that_declares_a_reader_can_extend_its_allowlist():
    """Both vectors (`args` and the `plain_args` fallback) carry the grant flag
    the reader is added to, so no row can declare a reader it cannot grant."""
    for one in harness_mod.KNOWN:
        if one.reader is None:
            continue
        assert one.reader.grant_flag in one.args, one.id
        if one.plain_args:
            assert one.reader.grant_flag in one.plain_args, one.id
        assert one.reader.config_flag.startswith("--"), one.id
        assert "{server}" in one.reader.tool and "{tool}" in one.reader.tool, one.id


def test_the_rows_that_declare_a_reader_are_a_row_fact_not_a_name_check():
    """Claude Code is the row verified end to end (its `--help` declares
    `--mcp-config`, its docs give `mcp__<server>__<tool>`); the others stay as
    they were until a row is verified the same way. Recorded so a new row is a
    decision, not an accident."""
    with_reader = {one.id for one in harness_mod.KNOWN if one.reader is not None}
    assert with_reader == {"claude-code"}


# ── the per-run config ───────────────────────────────────────────────────────


def test_a_run_gets_its_own_reader_config_in_its_own_folder(monkeypatch):
    _declares(monkeypatch)
    researcher = HarnessResearcher(_claude())
    with researcher._workspace():
        folder = Path(researcher._run_cwd)
        written = Path(researcher._reader_config)
        assert written.parent == folder
        config = json.loads(written.read_text(encoding="utf-8"))
    assert config == {"mcpServers": {"exa": {"type": "http", "url": "https://mcp.exa.ai/mcp"}}}
    # It goes with the folder, and the reader's own config is never the target.
    assert not folder.exists()
    assert researcher._reader_config == ""


def test_the_config_holds_the_page_reader_and_nothing_of_krikos(monkeypatch):
    """Kriko's own MCP tools stay out of the spawned agent (findings come back
    on stdout, one acceptance path), and so does anything else."""
    config = harness_mod.reader_config()
    assert list(config["mcpServers"]) == [harness_mod.READER_SERVER]
    assert "kriko" not in json.dumps(config).lower()
    assert harness_mod.READER_TOOLS == ("web_fetch_exa",)


def test_no_folder_gets_a_reader_config_where_the_flag_is_not_declared(monkeypatch):
    _declares(monkeypatch, DECLARED - {"--mcp-config"})
    researcher = HarnessResearcher(_claude())
    with researcher._workspace():
        assert researcher._reader_config == ""
        assert list(Path(researcher._run_cwd).iterdir()) == []


def test_only_a_row_with_a_reader_gets_a_reader_config(monkeypatch):
    """Every other CLI's per-run folder holds what it held before."""
    monkeypatch.setattr(harness_mod, "declared", lambda _: frozenset({"--mcp-config"}))
    for one in harness_mod.KNOWN:
        if one.sandbox_home:
            continue
        researcher = HarnessResearcher(one)
        with researcher._workspace():
            held = {p.name for p in Path(researcher._run_cwd).iterdir()}
        if one.reader is not None:
            assert harness_mod.READER_CONFIG_FILE in held, one.id
        else:
            assert harness_mod.READER_CONFIG_FILE not in held, one.id


# ── the brief ────────────────────────────────────────────────────────────────


def test_the_note_names_the_tool_and_says_what_a_refusal_costs():
    note = harness_mod.page_reader_note([READER_TOOL])
    assert "web_fetch_exa" in note and READER_TOOL in note
    assert "once" in note
    assert "does not count" in note
    assert "another source" in note  # the way out if the reader is refused too
    assert "—" not in note


def test_the_note_sits_beside_the_refused_page_line_once():
    brief = "Look.\n\n" + REFUSED_PAGE + "\n\nReply."
    said = harness_mod.with_page_reader(brief, [READER_TOOL])
    assert said.count(REFUSED_PAGE) == 1
    at = said.index(REFUSED_PAGE) + len(REFUSED_PAGE)
    assert said[at:].lstrip().startswith("The one exception")
    assert said.count("The one exception") == 1
    assert harness_mod.with_page_reader(said, [READER_TOOL]) == said


def test_kriko_the_engine_names_no_reader():
    """The engine's wording says what a refusal means and nothing about which
    tool answers it: that is the harness layer's to add, per run."""
    low = REFUSED_PAGE.lower()
    assert "exa" not in low and "mcp" not in low and "reader" not in low


def test_the_quick_look_does_not_count_a_refused_page_as_an_opened_one():
    """The reader's log: "Three of my page fetches returned 403 errors, which
    used up my three page opens." The budget is for pages that load."""
    text = quicklook.brief("A thing")
    budget = next(item for item in text.split("\n* ") if "at most three" in item)
    assert "refuses" in budget and "does not count" in budget
    assert "—" not in budget
    assert text.count(REFUSED_PAGE) == 1


# ── through the real spawn ───────────────────────────────────────────────────


def _reporting_cli(tmp_path: Path, reader: PageReader | None) -> Harness:
    """A child that answers with its argv, the config file it was pointed at,
    and the prompt it was given, read while the run's folder still exists."""
    script = tmp_path / "report.py"
    script.write_text(
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        "config = ''\n"
        "if '--mcp-config' in argv:\n"
        "    config = open(argv[argv.index('--mcp-config') + 1], encoding='utf-8').read()\n"
        "print(json.dumps({'type': 'result', 'result': json.dumps({"
        "'argv': argv, 'config': config, 'prompt': argv[-1]})}))\n",
        encoding="utf-8")
    return Harness("fake", "Fake CLI", sys.executable,
                   (str(script), "--allowedTools", "WebSearch,WebFetch"),
                   structured=True, reader=reader)


READER = PageReader("--mcp-config", "--allowedTools", "mcp__{server}__{tool}")


def _ask(tmp_path, monkeypatch, reader, flags, brief=None):
    monkeypatch.setattr(harness_mod, "declared", lambda _: frozenset(flags))
    one = _reporting_cli(tmp_path, reader)
    brief = brief or f"look at it\n\n{REFUSED_PAGE}\n\nreply"
    return json.loads(HarnessResearcher(one, timeout=30).ask(brief))


def test_a_run_hands_the_child_the_config_the_grant_and_the_note(tmp_path, monkeypatch):
    got = _ask(tmp_path, monkeypatch, READER, {"--mcp-config"})
    argv = got["argv"]
    assert json.loads(got["config"])["mcpServers"]["exa"]["type"] == "http"
    assert argv[argv.index("--allowedTools") + 1] == f"WebSearch,WebFetch,{READER_TOOL}"
    assert "The one exception" in got["prompt"]
    assert got["prompt"].count(REFUSED_PAGE) == 1


def test_a_run_the_cli_cannot_take_a_reader_on_says_nothing_of_one(tmp_path, monkeypatch):
    """The note is only true when the tool is there, so it is only said then."""
    got = _ask(tmp_path, monkeypatch, READER, set())
    assert "--mcp-config" not in got["argv"] and got["config"] == ""
    assert "The one exception" not in got["prompt"]
    assert got["prompt"].count(REFUSED_PAGE) == 1


def test_a_row_with_no_reader_gets_no_reader(tmp_path, monkeypatch):
    got = _ask(tmp_path, monkeypatch, None, {"--mcp-config"})
    assert "--mcp-config" not in got["argv"]
    assert "The one exception" not in got["prompt"]
    assert got["argv"][got["argv"].index("--allowedTools") + 1] == "WebSearch,WebFetch"


# ── the log ──────────────────────────────────────────────────────────────────


def test_a_page_read_through_the_reader_says_so_in_the_log():
    event = {"type": "assistant", "message": {"content": [{
        "type": "tool_use", "name": READER_TOOL,
        "input": {"urls": ["https://shop.example/review"], "maxCharacters": 12000},
    }]}}
    line = harness_mod.narrate(event)
    assert line == "read through the page reader https://shop.example/review"


def test_an_ordinary_fetch_is_still_a_fetch_in_the_log():
    event = {"type": "assistant", "message": {"content": [{
        "type": "tool_use", "name": "WebFetch", "input": {"url": "https://shop.example/a"},
    }]}}
    assert harness_mod.narrate(event) == "fetched https://shop.example/a"


def test_the_start_line_says_whether_the_reader_connected():
    """The one thing a reader of the log cannot otherwise tell: a page reader
    that never loaded looks exactly like one that was never asked."""
    up = {"type": "system", "subtype": "init", "model": "m",
          "mcp_servers": [{"name": "exa", "status": "connected"}]}
    down = {"type": "system", "subtype": "init", "model": "m",
            "mcp_servers": [{"name": "exa", "status": "failed"}]}
    assert harness_mod.narrate(up) == "started m; exa connected"
    assert harness_mod.narrate(down) == "started m; exa failed"
    assert harness_mod.narrate({"type": "system", "subtype": "init", "model": "m"}) == "started m"


# ── the real CLI, for free ───────────────────────────────────────────────────


def test_the_real_cli_accepts_the_reader_vector(tmp_path):
    """The empty-prompt trick `test_the_harness_command_line_is_one_the_cli_
    accepts` uses: the CLI judges the whole vector, reader flags included, and
    refuses only for the missing prompt, before any API call."""
    import subprocess

    one = harness_mod.chosen("claude-code")
    if one is None:
        pytest.skip("no Claude Code on this machine")
    if not harness_mod.reader_attachable(one):
        pytest.skip("this Claude Code does not declare --mcp-config")
    config = tmp_path / harness_mod.READER_CONFIG_FILE
    config.write_text(json.dumps(harness_mod.reader_config()), encoding="utf-8")
    done = subprocess.run(  # noqa: S603 - fixed executable, no shell
        [*harness_mod.command_for(one, reader_config=str(config)), "--", ""],
        input="", capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
    )
    said = (done.stderr or "") + (done.stdout or "")
    assert "unknown option" not in said, said[:400]
    assert "is invalid" not in said, said[:400]
    assert "Invalid MCP configuration" not in said, said[:400]
    assert "Input must be provided" in said, said[:400]
