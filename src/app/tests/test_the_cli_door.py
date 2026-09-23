"""`kriko agenda / brief / submit` — the research door that is not MCP.

The MCP server failed to connect while the CLI beside it worked, which is the
whole argument for a second door. A second door is only safe if it is the
*same* path with a different label, so every assertion here is a comparison
with the MCP tool of the same name, on the same store.
"""

# ruff: noqa: F811 — `store` is a fixture imported from test_mcp_server, so each test redefines it by name.
import json
import sqlite3

from app import cli, mcp_server
from app.tests.test_mcp_server import _finding, _subject, store  # noqa: F401 — fixture


def _run(capsys, *argv) -> dict:
    assert cli.main(list(argv)) == 0
    return json.loads(capsys.readouterr().out)


def test_submit_through_the_cli_keeps_what_mcp_keeps(store, tmp_path, capsys):
    path = tmp_path / "findings.json"
    path.write_text(json.dumps([_finding()]), encoding="utf-8")

    result = _run(capsys, "--store", str(store), "submit", _subject(), str(path),
                  "--pack", "tools", "--query", "makita DHP484 chuck")

    assert result["rejected"] == []
    assert len(result["accepted"]) == 1
    assert mcp_server.store_status()["claims"] == 2


def test_an_ungrounded_quote_is_refused_at_the_cli_door_too(store, tmp_path, capsys):
    """The rule the evidence chain rests on does not depend on the door."""
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(
        {"findings": [_finding(quote="the motor catches fire within a week")]}
    ), encoding="utf-8")

    result = _run(capsys, "--store", str(store), "submit", _subject(), str(path),
                  "--pack", "tools")

    assert result["accepted"] == []
    assert "verbatim" in result["rejected"][0]["reason"]
    assert mcp_server.store_status()["claims"] == 1


def test_the_cli_door_is_labelled_cli_in_the_feed(store, tmp_path, capsys):
    path = tmp_path / "findings.json"
    path.write_text(json.dumps([_finding()]), encoding="utf-8")
    _run(capsys, "--store", str(store), "submit", _subject(), str(path),
         "--pack", "tools")

    conn = sqlite3.connect(store.parent / "app.sqlite")
    doors = {r[0] for r in conn.execute("SELECT door FROM operations")}
    submitted = {r[0] for r in conn.execute("SELECT door FROM submissions")}
    conn.close()
    assert doors == {"cli"}
    assert submitted == {"cli"}


def test_brief_and_agenda_answer_what_the_mcp_tools_answer(store, capsys):
    assert _run(capsys, "--store", str(store), "brief", _subject(),
                "--pack", "tools") == mcp_server.research_brief(_subject(), "tools")

    via_cli = _run(capsys, "--store", str(store), "agenda", "--pack", "tools")
    via_mcp = mcp_server.research_agenda(pack_id="tools")
    assert [r.get("subject_id") for r in via_cli["rows"]] == [
        r.get("subject_id") for r in via_mcp["rows"]
    ]
