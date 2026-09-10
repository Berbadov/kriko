"""B96 — an agent can start a pack, and only the reader can install one.

The reader's sentence was "the pack building must be guided with agents", and
the gap behind it was narrower than it sounds. Scaffolding was already
reader-reachable (`POST /api/packs/scaffold`, one press on the Jobs screen);
what an *agent* could write was three tools wide, and `submit_findings` — the
only one of them that adds knowledge — can only add claims to a subject some
pack already declares. So the one job that most wants an agent, modelling a
category nobody has modelled yet, was the one job it could not begin.

Two gates, and they pull in opposite directions on purpose:

* **Parity** — everything a reader can do to a pack, an agent can do too.
  A door that exists on one side only is how the previous gap happened.
* **Confinement** — and nothing more than that. An agent writes data files
  into one directory and cannot write code, cannot escape the directory, and
  cannot put anything in the reader's store. The reader's press is what
  installs, and only the reader can throw a draft away.

The third gate is the one that goes stale: the generated skill must name every
write tool the server registers. A tool an agent is never told about is a tool
that does not exist, and this project has already shipped prose naming two
tools that had been deleted.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import mcp_server, packdraft
from app.web.app import create_app
from app.web.settings import Settings

IDENTITY = {"product": ["brand", "series"]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point both the MCP tools and the app at one temporary store."""
    path = tmp_path / "k.sqlite"
    monkeypatch.setattr(mcp_server, "STORE_PATH", path)
    return path


@pytest.fixture
def client(store, tmp_path):
    app = create_app(
        Settings(
            store_path=store,
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


def _tools() -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}


# ── parity ───────────────────────────────────────────────────────────────


def test_an_agent_can_do_everything_to_a_pack_that_a_reader_can(client, store):
    """Start it, fill it in, build it. The same three steps, through MCP."""
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    assert any(name.endswith("pack.toml") for name in made["files"])

    mcp_server.write_draft_file(
        made["draft"],
        "research/principle.md",
        "# What this pack surfaces\n\nOnly what an inspection would not catch.\n",
    )
    built = mcp_server.build_draft(made["draft"])
    assert built["artifact"].endswith(".kpack")

    # And the reader sees it, with what they need to decide.
    listed = client.get("/api/packs/drafts").json()["items"]
    assert [row["pack_id"] for row in listed] == ["org.example.thing"]
    assert listed[0]["error"] == ""
    assert "research/principle.md" in listed[0]["files"]


def test_the_agents_draft_installs_from_the_readers_press_and_not_before(
    client, store
):
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)

    # Drafting, writing and building put nothing in the store.
    mcp_server.write_draft_file(made["draft"], "README.md", "# Things\n\nRows.\n")
    mcp_server.build_draft(made["draft"])
    assert client.get("/api/packs").json() == []

    installed = client.post(f"/api/packs/drafts/{made['draft']}/install")
    assert installed.status_code == 200
    assert installed.json()["pack_id"] == "org.example.thing"
    assert [pack["pack_id"] for pack in client.get("/api/packs").json()] == [
        "org.example.thing"
    ]


def test_installing_a_draft_needs_no_separate_build_first(client, store):
    """One decision, one press. The artifact's lifecycle is not the reader's."""
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    assert client.get("/api/packs/drafts").json()["items"][0]["artifact"] is None
    assert client.post(f"/api/packs/drafts/{made['draft']}/install").status_code == 200


def test_only_the_reader_can_throw_a_draft_away(client, store):
    """No agent tool deletes a draft, and the reader's delete works.

    An agent that could remove the evidence of what it wrote would be worse
    than one that cannot; rewriting the file it got wrong is the whole of what
    it needs.
    """
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    names = _tools()
    assert not [
        name
        for name in names
        if "draft" in name and ("delete" in name or "discard" in name)
    ]

    gone = client.delete(f"/api/packs/drafts/{made['draft']}")
    assert gone.status_code == 200
    assert client.get("/api/packs/drafts").json()["items"] == []


def test_discarding_a_draft_leaves_an_installed_pack_alone(client, store):
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    client.post(f"/api/packs/drafts/{made['draft']}/install")
    client.delete(f"/api/packs/drafts/{made['draft']}")
    assert [pack["pack_id"] for pack in client.get("/api/packs").json()] == [
        "org.example.thing"
    ]


# ── confinement ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "build.py",
        "pipeline/run.py",
        "coverage.py",
        "../../.claude/settings.json",
        "data/../../escape.yaml",
        "/etc/passwd",
        "data/rows.yaml.py",
        "research/principle.md.sh",
        "data/nested/rows.yaml",
        "",
    ],
)
def test_a_draft_holds_data_and_never_code_or_a_path_out_of_itself(store, path):
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    with pytest.raises(packdraft.DraftRefused):
        mcp_server.write_draft_file(made["draft"], path, "anything")


def test_the_directory_is_derived_from_the_pack_id_and_never_from_the_caller(store):
    """An agent that could name the directory would eventually name one `..`."""
    made = mcp_server.draft_pack("org.example.Thing/../../x", "Things", IDENTITY)
    root = packdraft.drafts_root(store).resolve()
    assert root in (root / made["draft"]).resolve().parents
    assert "/" not in made["draft"] and ".." not in made["draft"]


def test_an_id_that_reduces_to_nothing_is_refused_rather_than_defaulted(store):
    with pytest.raises(packdraft.DraftRefused):
        mcp_server.draft_pack("///", "Things", IDENTITY)


def test_a_second_draft_of_the_same_pack_does_not_overwrite_the_first(store):
    mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    with pytest.raises(FileExistsError):
        mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)


def test_one_file_cannot_fill_the_disk(store):
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    with pytest.raises(packdraft.DraftRefused):
        mcp_server.write_draft_file(
            made["draft"], "data/rows.yaml", "x" * (packdraft.MAX_BYTES + 1)
        )


def test_writing_to_a_draft_that_does_not_exist_says_so(store):
    with pytest.raises(packdraft.DraftRefused):
        mcp_server.write_draft_file("nothing-here", "README.md", "hi")


def test_a_draft_that_stopped_loading_is_listed_with_its_reason(client, store):
    """Listed, not hidden: installing it will fail and the agent must be told."""
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    mcp_server.write_draft_file(made["draft"], "pack.toml", "this is not toml [[[")
    row = client.get("/api/packs/drafts").json()["items"][0]
    assert row["error"]
    assert client.post(f"/api/packs/drafts/{made['draft']}/install").status_code == 400


# ── the skill has to name the tools ──────────────────────────────────────


def test_every_write_tool_the_server_exposes_is_named_in_the_skill(client, store):
    """Prose has no compiler, so this is one.

    Kriko has already shipped a brief naming two tools that had been deleted;
    the same drift in the other direction — a tool nothing tells the agent
    about — is invisible instead of broken, which is worse.
    """
    from app import agentskill
    from kriko.store.db import connect

    # A pack has to be installed for the *research* half of the skill to be
    # rendered at all — the empty-installation variant is deliberately
    # authoring-only, and is checked separately below.
    made = mcp_server.draft_pack("org.example.thing", "Things", IDENTITY)
    client.post(f"/api/packs/drafts/{made['draft']}/install")
    conn = connect(store)
    try:
        skill = agentskill.render(conn)
    finally:
        conn.close()

    writes = [
        name
        for name in _tools()
        if name.startswith(("submit_", "draft_", "write_", "build_", "install_", "set_"))
    ]
    assert "draft_pack" in writes  # the list is derived; this is the canary
    missing = [name for name in writes if name not in skill]
    # `install_pack` and `set_pack_enabled` are the reader's presses in the UI
    # and are documented on the Connect screen rather than in the skill.
    assert missing == ["install_pack", "set_pack_enabled"], missing


def test_the_generated_harness_grant_covers_the_authoring_tools():
    """A tool the checked-in agent file does not grant is not callable.

    `packs/cars/pipeline/agent/render.py` is what writes `.claude/agents/` and
    `.opencode/agents/`, and its list going stale is how a granted surface and
    a live surface drift apart.
    """
    from packs.cars.pipeline.agent import render

    live = set(_tools())
    granted = set(render.MCP_TOOLS)
    assert not granted - live, f"granted but not registered: {granted - live}"
    for name in ("draft_pack", "write_draft_file", "build_draft", "list_pack_drafts"):
        assert name in granted


def test_an_empty_installation_is_told_to_author_rather_than_to_research(store):
    """The reader's other sentence: "no agents guidline for brand new packages"."""
    from app import agentskill
    from kriko.store.db import connect

    conn = connect(store)
    try:
        skill = agentskill.render(conn)
    finally:
        conn.close()
    assert skill and "draft_pack" in skill
    assert "## The loop" not in skill
