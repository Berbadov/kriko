"""The brief budgets its run and remembers the runs before it.

Two things a one-shot brief could not do, both of which the research loop
needs: say how much run is being bought (a brief that asks for depth without
naming a number is what searches endlessly and stops nowhere), and start
from what earlier runs on this subject learned (which searches earned their
keep, which went nowhere, what the refusals said) instead of re-running
their dead ends.

Asserted here:

* both efforts state a budget, and they state different ones;
* a word that is neither effort is refused to the agent rather than
  rendered as a budget that means nothing;
* the memory section renders from the submission log, and a missing log is
  no memory rather than no brief;
* the skill names both efforts, the self-grade, and the already-known
  verdict — the loop's whole protocol is teachable in one document.
"""

import textwrap

import pytest

from app import agentops, agentskill, mcp_server
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TOML = """
[pack]
id = "tools"
name = "Tools"
version = "0.1.0"
[identity]
product = ["brand", "model"]
"""

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model, role: attribute, datatype: text, match: {required: true}}
- {term_id: mech, role: domain}
"""

SUBJECTS = """
- kind: product
  label: Widget 100
  identity: {brand: acme, model: w100}
"""

GATES = """
limits:
  - {pattern: min_rationale_chars, note: "60"}
"""

TEMPLATES = '- "Widget 100 common faults"\n'

DOCUMENT = (
    "The bearing housing cracks after about 800 hours of use, and replacing it "
    "means splitting the case, which is most of the cost of a new unit."
)
QUOTE = "The bearing housing cracks after about 800 hours of use"

GOOD = (
    "The housing is not a serviceable part, so when it cracks the repair means "
    "splitting the case and costs close to a replacement. Ask how many hours "
    "this one has done before you agree a price."
)


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "vocabulary" / "gates.yaml").write_text(GATES, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text("[]", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text(TEMPLATES, encoding="utf-8")
    conn = connect(tmp_path / "s.sqlite")
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    yield conn
    conn.close()


@pytest.fixture
def app_state_path(tmp_path):
    return tmp_path / "app.sqlite"


def _subject(store):
    return store.execute("SELECT subject_id FROM subjects").fetchone()["subject_id"]


def _finding(**over):
    return {
        "title": "Bearing housing cracks after 800 hours",
        "domain": "mech",
        "severity": "high",
        "quote": QUOTE,
        "source_url": "https://maker.example.com/tsb/1",
        "document_text": DOCUMENT,
        "component": "bearing housing",
        **over,
    }


def _brief(store, app_state_path, effort="fast"):
    return agentops.brief(store, _subject(store), "tools",
                          effort=effort, app_state_path=app_state_path)


# ── the budget ───────────────────────────────────────────────────────────


def test_a_fast_run_states_its_budget(store, app_state_path):
    out = _brief(store, app_state_path, effort="fast")
    assert out["mode"] == "fast"
    assert "How much run this is (fast)" in out["brief"]
    assert "minutes-long job" in out["brief"]


def test_a_deep_run_budgets_a_tree(store, app_state_path):
    out = _brief(store, app_state_path, effort="deep")
    assert out["mode"] == "deep"
    body = out["brief"]
    assert "How much run this is (deep)" in body
    assert "at most 4 parallel search threads" in body, (
        "a deep run without numbers is the endless-search failure mode"
    )
    assert "follow-up queries per open domain" in body


def test_the_budgets_are_not_the_same_document(store, app_state_path):
    fast = _brief(store, app_state_path, "fast")["brief"]
    deep = _brief(store, app_state_path, "deep")["brief"]
    assert fast != deep
    assert "How to read" in fast and "How to read" in deep, (
        "the reading strategy belongs to both efforts, not to one"
    )
    assert "Sources, best first" in fast, "the source rubric is not optional"


def test_an_unknown_effort_is_refused_rather_than_rendered(store, tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(mcp_server, "STORE_PATH", tmp_path / "s.sqlite")
    out = mcp_server.research_brief(_subject(store), "tools", mode="bogus")
    assert out == {"error": "mode must be fast or deep, not 'bogus'"}


def test_the_mcp_brief_still_works_with_no_mode(store, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "STORE_PATH", tmp_path / "s.sqlite")
    out = mcp_server.research_brief(_subject(store), "tools")
    assert out["mode"] == "fast"
    assert "How much run this is (fast)" in out["brief"]


# ── the memory ────────────────────────────────────────────────────────────


def test_the_brief_remembers_what_earlier_runs_did(store, app_state_path):
    """One dead run, then one that kept a finding — and the third brief says both."""
    subject = _subject(store)
    # Run one: a refusal with a fix, and a search that led to nothing kept.
    agentops.submit(store, app_state_path=app_state_path, door="test",
                    subject_id=subject, pack_id="tools",
                    findings=[_finding()],  # no rationale: refused, repairable
                    queries=["widget 100 teardown", "Widget 100 common faults"])
    # Run two: a kept finding, found by its own query.
    agentops.submit(store, app_state_path=app_state_path, door="test",
                    subject_id=subject, pack_id="tools",
                    findings=[_finding(rationale=GOOD,
                                       source_url="https://maker.example.com/tsb/2")],
                    queries=["bearing housing crack forum"])
    body = _brief(store, app_state_path)["brief"]
    assert "What earlier runs on this subject did" in body
    assert "2 submit(s) before this one kept 1 and lost 1" in body, (
        "the counts are the first thing a run should know about its past"
    )
    assert "Searches that led to kept findings: 'bearing housing crack forum'" in body
    assert "Searches that led to nothing kept" in body
    assert "'widget 100 teardown'" in body, "the dead end is named so it is not rerun"
    assert "rationale is 0 chars" in body, (
        "the refusal that happened once must be written past the next time"
    )


def test_a_brief_with_no_log_remembers_nothing_and_is_still_a_brief(store,
                                                                    tmp_path):
    body = _brief(store, tmp_path / "nowhere.sqlite")["brief"]
    assert "What earlier runs on this subject did" not in body
    assert "What makes a claim worth keeping" in body


def test_a_first_run_gets_no_memory_section(store, app_state_path):
    body = _brief(store, app_state_path)["brief"]
    assert "What earlier runs on this subject did" not in body


# ── the reading strategy, in both efforts ────────────────────────────────


def test_the_brief_teaches_extract_then_verify_and_the_self_grade(
        store, app_state_path):
    body = _brief(store, app_state_path)["brief"]
    assert "copy the quote while the page is open" in body
    assert "Drop the ones you would refuse yourself" in body, (
        "the self-grade is the one quality pass that runs before storage"
    )
    assert "dead end" in body, "a twice-empty query is a lesson, not a habit"


# ── the skill carries the same protocol ───────────────────────────────────


def test_the_skill_names_both_efforts_the_self_grade_and_the_verdicts(store):
    body = agentskill.render(store) or ""
    assert "fast or deep" in body
    assert "refuse yourself" in body, (
        "the self-grade is the one quality pass that runs before storage"
    )
    assert "already known" in body, (
        "the agent must be told the third verdict before it meets one"
    )
