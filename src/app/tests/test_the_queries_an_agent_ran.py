"""B95 — the agent decides the queries, and the pack finds out which ones.

The reader's complaint was two sentences long and contained two different
defects: "the researches making turkish-english queries" (B94, fixed in the
manifest) and "agent should decide the queries" — this one. Handing an agent
latitude is the easy half; the half that makes it worth anything is asking
which searches it actually chose, because a pack whose seeds are never
compared against what replaced them cannot improve.

So the gate here is *agreement between the two doors*. The brief an MCP agent
reads and the contract a harness-driven agent reads are written in different
files for different call shapes, and if only one of them grants the latitude —
or only one of them asks for the queries back — an author's picture of what
their seeds are doing depends on which door the researcher came in. That is
the same class of bug as a claim's provenance depending on its door, which
this project already refuses.
"""

import json

import pytest

from app.providers import harness
from app.web import state
from kriko.research import ResearchTask
from kriko.research.agent import AgentResearcher


def _task(**kw) -> ResearchTask:
    base = dict(
        subject_id="s1", subject_label="Makita DHP484", subject_kind="product",
        pack_id="drill", identity={"brand": "makita", "model": "DHP484"},
        attribution_aliases=("DHP484Z",), search_aliases=("DHP 484",),
        queries=("{alias} common problems", "{label} failure symptoms"),
        value_principle="Keep only what an inspection would not catch.",
        domains=("mechanical", "battery"), max_documents=3,
    )
    base.update(kw)
    return ResearchTask(**base)


# ── the gate: both doors grant the same latitude ─────────────────────────


def test_the_brief_and_the_harness_contract_agree_on_the_agents_latitude():
    """Seeds in both, or seeds in neither.

    Asserted on the *rendered* brief rather than on the source, because the
    brief is assembled from a pack's rows and a paragraph that never reaches
    the agent grants nothing.
    """
    brief = AgentResearcher().brief(_task())
    assert "not a script" in brief
    assert "not a script" in harness.CONTRACT
    # And both must ask for the queries back, in the shape their own door
    # takes them: a keyword argument through MCP, a JSON key on stdout.
    assert "queries=[...]" in brief
    assert '"queries"' in harness.CONTRACT


def test_both_doors_say_the_queries_do_not_decide_whether_a_finding_is_kept():
    """An agent that thinks its query list is being graded will edit it.

    Which would make the one number this feature exists to produce a fiction.
    """
    brief = AgentResearcher().brief(_task())
    for text in (brief, harness.CONTRACT):
        assert "no effect on whether a finding is kept" in text


def test_the_mcp_tool_takes_the_queries_the_brief_promises_it_will():
    """The brief prints a call signature. It has to be callable."""
    from app import mcp_server

    import inspect

    signature = inspect.signature(mcp_server.submit_findings)
    assert "queries" in signature.parameters
    # Optional, because the MCP door predates the parameter and a client that
    # omits it must still be able to submit.
    assert signature.parameters["queries"].default is None


# ── what happens to them ─────────────────────────────────────────────────


def test_a_batch_remembers_what_was_searched_for(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    state.record_submission(
        conn, door="job", subject_id="s1", pack_id="drill",
        verdicts={"accepted": [{"title": "a", "claim_id": "c1"}], "rejected": []},
        queries=["DHP484 chuck wobble", "DHP484 arıza"],
    )
    kept = state.submissions(conn)[0]
    assert kept["queries"] == ["DHP484 chuck wobble", "DHP484 arıza"]


def test_a_door_that_cannot_say_still_writes_its_verdicts_down(tmp_path):
    """The column arrived after the table. An older row is not a broken row."""
    conn = state.connect(tmp_path / "app.sqlite")
    state.record_submission(
        conn, door="mcp", subject_id="s1", pack_id="drill",
        verdicts={"accepted": [], "rejected": [{"title": "a", "reason": "no"}]},
    )
    assert state.submissions(conn)[0]["queries"] == []
    assert state.query_shapes(conn) == []


def test_the_shapes_are_ranked_by_what_they_kept(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    for queries, accepted in (
        (["weak shape"], 0),
        (["strong shape"], 3),
        (["strong shape", "weak shape"], 1),
    ):
        state.record_submission(
            conn, door="job", subject_id="s1", pack_id="drill",
            verdicts={
                "accepted": [{"title": str(i), "claim_id": f"c{i}"}
                             for i in range(accepted)],
                "rejected": [],
            },
            queries=queries,
        )
    shapes = state.query_shapes(conn)
    assert [s["query"] for s in shapes] == ["strong shape", "weak shape"]
    assert shapes[0]["accepted"] == 4
    assert shapes[0]["batches"] == 2
    assert shapes[1]["accepted"] == 1


def test_a_migrated_installation_gains_the_column_rather_than_losing_the_rows(
    tmp_path,
):
    """`add_missing_columns` is the only migration this file allows itself.

    A reader's submission history is theirs; a new column must not be bought
    by dropping the table that holds it.
    """
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    conn.execute("ALTER TABLE submissions RENAME TO submissions_old")
    conn.execute(
        "CREATE TABLE submissions (submission_id TEXT PRIMARY KEY,"
        " created_at TEXT NOT NULL, door TEXT NOT NULL, subject_id TEXT NOT NULL,"
        " pack_id TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0,"
        " refused INTEGER NOT NULL DEFAULT 0, verdicts_json TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO submissions VALUES ('old','2026-01-01T00:00:00Z','mcp',"
        "'s1','drill',1,0,?)",
        (json.dumps({"accepted": [{"title": "a", "claim_id": "c1"}]}),),
    )
    conn.commit()
    added = state.add_missing_columns(conn)
    assert "submissions.queries_json" in added
    kept = state.submissions(conn)
    assert [row["submission_id"] for row in kept] == ["old"]
    assert kept[0]["queries"] == []


# ── the harness plane's own account ──────────────────────────────────────


def test_the_harness_reports_the_searches_it_says_it_ran(monkeypatch):
    researcher = harness.HarnessResearcher(harness.KNOWN[0])
    monkeypatch.setattr(
        harness.HarnessResearcher,
        "_run",
        lambda self, prompt: json.dumps(
            {"queries": ["  adapted query  ", "", 7], "findings": []}
        ),
    )
    researcher.gather(_task())
    # Blanks dropped, whitespace trimmed, a non-string coerced rather than
    # crashing a completed run of real research.
    assert researcher.queries_run == ["adapted query", "7"]


@pytest.mark.parametrize("reported", ["not a list", None, {}])
def test_a_harness_that_reports_nothing_usable_reports_nothing(
    monkeypatch, reported
):
    researcher = harness.HarnessResearcher(harness.KNOWN[0])
    monkeypatch.setattr(
        harness.HarnessResearcher,
        "_run",
        lambda self, prompt: json.dumps({"queries": reported, "findings": []}),
    )
    researcher.gather(_task())
    assert researcher.queries_run == []


def test_the_run_records_the_agents_queries_over_the_packs_templates():
    """The whole point of B95, as one assertion.

    A plane that adapts its queries has an account of what it ran, and that
    account is what the submission row keeps. A plane that runs the templates
    literally has no account, and then the templates are the truth.
    """
    from app.web.tasks import _queries_run

    task = _task()

    class Adapted:
        queries_run = ["DHP484 chuck play forum", " ", 12]

    class Literal:
        pass

    assert _queries_run(Adapted(), task) == ["DHP484 chuck play forum", "12"]
    assert _queries_run(Literal(), task) == list(task.rendered_queries())
