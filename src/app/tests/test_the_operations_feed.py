"""B122 — what an agent is doing, live, whichever door it came in.

The reader's own coding agent, talking to Kriko's MCP server, is the door they
prefer and the one the app was blindest to: an operation there was visible only
afterwards, only as a `submissions` row, and only when the operation happened to
*be* a submission. A `lookup`, a `research_brief`, a `draft_pack` left no trace
at all. B121 fixed this for runs Kriko starts; this is the other half.

Three properties are load-bearing, and each is a test below: the row opens
before the work (so a call in flight is visible, and a hung one is too),
recording can never change the outcome of the call it is recording, and a page
of `document_text` never lands in this table.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import operations
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


@pytest.fixture
def conn(settings):
    return state.connect(settings.app_state_path)


def test_a_call_is_a_row_before_it_is_an_answer(settings, conn):
    """The difference between a feed and a log.

    Inside the body the row already exists and says `running` — which is what
    makes a forty-second tool call visible for forty seconds instead of
    appearing, finished, at the end."""
    with operations.record(
        settings.app_state_path, door="mcp", name="lookup", arguments={"pack_id": "p"}
    ) as outcome:
        (live,) = state.operations(conn)
        assert live["state"] == "running"
        assert live["name"] == "lookup"
        assert state.running_operations(conn) == 1
        outcome["response"] = "{}"
    (done,) = state.operations(conn)
    assert done["state"] == "ok"
    assert done["ms"] is not None


def test_a_failure_is_recorded_and_still_raised(settings, conn):
    """The caller's error handling is not this module's business."""
    with pytest.raises(ValueError):
        with operations.record(settings.app_state_path, door="mcp", name="lookup"):
            raise ValueError("no such pack")
    (row,) = state.operations(conn)
    assert row["state"] == "failed"
    assert "no such pack" in row["error"]


def test_recording_never_breaks_the_call_it_records(tmp_path):
    """A feed that can fail a tool call is worse than no feed.

    Pointed at a path that cannot be a database, the body still runs and still
    returns — the same rule `log_submission` follows, for the same reason."""
    unwritable = tmp_path / "not-a-dir" / "x" / "app.sqlite"
    unwritable.parent.mkdir(parents=True)
    unwritable.parent.chmod(0o500)
    seen = []
    try:
        with operations.record(unwritable, door="mcp", name="lookup"):
            seen.append("the body ran")
    finally:
        unwritable.parent.chmod(0o700)
    assert seen == ["the body ran"]


def test_a_page_of_document_text_never_reaches_this_table(settings, conn):
    """`submit_findings` carries whole pages. Keeping them here would
    duplicate the `documents` table and make the feed the largest thing in
    `app.sqlite` — so a long string is replaced by its own measurement."""
    page = "x" * 20000
    with operations.record(
        settings.app_state_path,
        door="mcp",
        name="submit_findings",
        arguments={"findings": [{"document_text": page, "quote": "a short one"}]},
    ):
        pass
    (row,) = state.operations(conn)
    assert page not in row["request_json"]
    assert "a short one" in row["request_json"]
    assert "+" in row["request_json"] and "chars" in row["request_json"]
    assert len(row["request_json"]) <= operations.MAX_SUMMARY_CHARS + 1


def test_an_api_key_never_reaches_the_feed(settings, conn):
    """This table is not audited by anything that redacts, and it is a
    reader's whole history kept forever. A tool that ever gets a credential
    argument must not turn it into a row on disk."""
    with operations.record(
        settings.app_state_path,
        door="mcp",
        name="whatever",
        arguments={
            "api_key": "sk-super-secret-value",
            "Authorization": "Bearer abc123",
            "user_token": "t-xyz",
            "subject_id": "s1",
        },
    ):
        pass
    (row,) = state.operations(conn)
    assert "sk-super-secret-value" not in row["request_json"]
    assert "Bearer abc123" not in row["request_json"]
    assert "t-xyz" not in row["request_json"]
    assert "s1" in row["request_json"], "an ordinary argument must still show"


def test_the_feed_is_bounded(settings, conn, monkeypatch):
    monkeypatch.setattr(state, "OPERATIONS_KEPT", 5)
    for index in range(12):
        with operations.record(settings.app_state_path, door="mcp", name=f"t{index}"):
            pass
    assert len(state.operations(conn, limit=100)) == 5


def test_a_row_still_running_at_startup_belongs_to_a_dead_process(settings, conn):
    """The MCP server is a *separate process* this one does not supervise, so
    a tool call that died with it would read as running forever."""
    state.open_operation(conn, door="mcp", kind="read", name="lookup")
    assert state.running_operations(conn) == 1
    assert state.interrupt_running_operations(conn) == 1
    assert state.running_operations(conn) == 0
    assert state.operations(conn)[0]["error"] == "interrupted"


def test_every_mcp_tool_is_recorded(tmp_path, monkeypatch):
    """Not only the three that write.

    "What is the agent doing right now" is answered by the reads as much as by
    the writes — a run that is looking things up and a run that is stuck look
    identical if only submissions are recorded."""
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "STORE_PATH", tmp_path / "k.sqlite")
    monkeypatch.setattr(mcp_server, "_app_state_path", lambda: tmp_path / "app.sqlite")
    mcp_server.list_packs()
    mcp_server.store_status()
    conn = state.connect(tmp_path / "app.sqlite")
    names = {row["name"] for row in state.operations(conn)}
    assert names == {"list_packs", "store_status"}
    assert all(row["door"] == "mcp" for row in state.operations(conn))


def test_a_tool_called_positionally_still_names_its_arguments(tmp_path, monkeypatch):
    """The feed says `subject_id=s1` however the client chose to call it."""
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "STORE_PATH", tmp_path / "k.sqlite")
    monkeypatch.setattr(mcp_server, "_app_state_path", lambda: tmp_path / "app.sqlite")
    mcp_server.list_subjects("org.kriko.cars")
    conn = state.connect(tmp_path / "app.sqlite")
    (row,) = state.operations(conn)
    assert json.loads(row["request_json"])["pack_id"] == "org.kriko.cars"
    assert row["pack_id"] == "org.kriko.cars"


def test_the_wrapper_does_not_change_what_a_tool_returns(tmp_path, monkeypatch):
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "STORE_PATH", tmp_path / "k.sqlite")
    monkeypatch.setattr(mcp_server, "_app_state_path", lambda: tmp_path / "app.sqlite")
    assert mcp_server.list_packs() == []
    assert isinstance(mcp_server.store_status(), dict)


def test_every_registered_tool_is_wrapped_by_the_recorder(tmp_path):
    """From the registry FastMCP actually serves, not a regex over the source.

    `registered_tools()`'s own docstring names the failure this replaces: a
    decorator rename could turn a source-text gate green on a server that no
    longer wraps anything. `functools.wraps` leaves `__wrapped__` pointing at
    the original function, which only `tool()`'s own `recorded` closure sets —
    a tool defined with a bare `@mcp.tool()` would have no such attribute.
    """
    from app import mcp_server

    tools = mcp_server.mcp._tool_manager.list_tools()
    assert tools, "the registry is empty -- this test cannot prove anything"
    unwrapped = [t.name for t in tools if not hasattr(t.fn, "__wrapped__")]
    assert unwrapped == [], f"registered without the operations recorder: {unwrapped}"


def test_the_tools_are_still_registered_after_wrapping(tmp_path):
    """A decorator applied in the wrong order registers nothing, and the MCP
    server would come up with an empty tool list that nothing else notices."""
    from app import mcp_server

    tools = mcp_server.mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    assert {"list_packs", "submit_findings", "lookup", "draft_pack"} <= names
    # And the description the agent reads is still the tool's own docstring,
    # not `functools.wraps`' idea of one.
    by_name = {tool.name: tool for tool in tools}
    assert "Installed packs" in (by_name["list_packs"].description or "")


def test_the_api_serves_the_feed_and_a_cursor(settings):
    client = TestClient(create_app(settings))
    with operations.record(settings.app_state_path, door="mcp", name="lookup"):
        pass
    first = client.get("/api/operations").json()
    assert first["items"][0]["name"] == "lookup"
    assert first["last_id"] == first["items"][0]["op_id"]
    # A cursor returns what came *after* it, so a poller cannot re-show a row.
    assert client.get(f"/api/operations?after_id={first['last_id']}").json()["items"] == []


def test_a_job_is_an_operation_too(settings):
    """A run and a tool call are the same kind of thing through two doors, and
    a feed that showed only one of them would hide exactly the comparison it
    exists to make possible."""
    client = TestClient(create_app(settings))
    client.post("/api/research", json={"subject_id": "nope"})
    for _ in range(200):
        rows = client.get("/api/operations").json()["items"]
        if rows and rows[0]["state"] != "running":
            break
    assert rows[0]["name"] == "research"
    assert rows[0]["door"] == "job"
    assert rows[0]["kind"] == "research"


def test_what_a_run_spent_reaches_the_row_and_nothing_else_becomes_a_zero():
    """A free run and an unpriced run are different facts.

    The column exists so the feed can answer "what did that cost"; it earns
    nothing if a handler that never counted is recorded as having counted
    nought, because that is the one answer the reader cannot tell apart from
    a genuinely free plane.
    """
    from app import operations

    assert operations.metered({"spent_usd": 0.42, "tokens": 1200}) == (0.42, 1200)
    assert operations.metered({"spent_usd": None, "tokens": None}) == (None, None)
    assert operations.metered({}) == (None, None)
    assert operations.metered(None) == (None, None)
    assert operations.metered({"spent_usd": "nonsense"}) == (None, None)
    assert operations.metered({"spent_usd": 0.0, "tokens": 0}) == (0.0, 0)
