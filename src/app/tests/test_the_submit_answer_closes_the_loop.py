"""The submit answer is the loop's turn, not a mailbox.

A submit used to answer with its verdicts and nothing else, so the agent's
next search — when it ran one — was a seed re-roll, the documented failure of
every budget-less research loop. Every system that researches well generates
its follow-up queries from the gap between what its bar demands and what the
current findings establish; Kriko's gap is computable without a model,
because the pack declares its domains and the store knows which of them the
subject holds claims in.

Asserted here:

* the verdict carries the coverage map — the pack's declared domains, split
  by whether this subject has claims in them, and the claim count;
* the verdict carries the next step, written at the model, and an empty one
  is the stop signal, not a silence the agent must interpret;
* both agent-facing documents teach the loop — the brief's reporting section
  and the skill's step list.
"""

import textwrap

import pytest

from app import agentskill
from app.findings import accept_findings, next_step
from kriko.pack import build
from kriko.research import plan_task
from kriko.research.agent import AgentResearcher
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
    for sub in ("vocabulary", "data"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "vocabulary" / "gates.yaml").write_text(GATES, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text("[]", encoding="utf-8")
    conn = connect(tmp_path / "s.sqlite")
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    yield conn
    conn.close()


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


def _submit(store, **over):
    return accept_findings(store, _subject(store), "tools", [_finding(**over)])


# ── the coverage map ─────────────────────────────────────────────────────


def test_a_fresh_subject_names_its_open_domains(store):
    """Even a refused batch answers for the store it leaves behind."""
    out = _submit(store)
    assert out["gaps"] == {
        "claims": 0,
        "domains_covered": [],
        "domains_empty": ["mech"],
    }
    assert "mech" in out["next"], "the next step must name the gap it came from"


def test_an_accepted_finding_closes_the_domain_the_answer_named(store):
    out = _submit(store, rationale=GOOD)
    assert out["accepted"]
    assert out["gaps"]["domains_covered"] == ["mech"]
    assert out["gaps"]["domains_empty"] == []
    assert out["gaps"]["claims"] == 1


# ── the next step ─────────────────────────────────────────────────────────


def test_nothing_to_do_is_an_empty_answer_not_a_silence(store):
    """The stop signal: an agent reading "" knows the map is closed."""
    out = _submit(store, rationale=GOOD)
    assert out["next"] == ""


def test_an_empty_next_step_is_earned_not_assumed():
    assert next_step([], []) == ""


def test_a_repairable_refusal_is_named_in_the_next_step(store):
    out = _submit(store)
    assert "one field short" in out["next"], out["next"]
    # And the loop it names can actually be run: the repair keeps the finding.
    again = _submit(store, rationale=GOOD)
    assert again["accepted"]
    assert again["next"] == ""


def test_a_fabricated_quote_never_becomes_a_repair_request(store):
    """Asking again would be asking it to try harder at inventing."""
    out = _submit(store, rationale=GOOD, quote="A sentence that is not in the page.")
    assert out["accepted"] == []
    assert "one field short" not in out["next"]


# ── the verifier's mechanical half: what the store already holds ─────────


def test_a_finding_the_store_holds_is_not_reaccepted_as_new_work(store):
    first = _submit(store, rationale=GOOD)
    claim = first["accepted"][0]["claim_id"]
    second = _submit(store, rationale=GOOD,
                     source_url="https://maker.example.com/tsb/2")
    assert second["accepted"] == [], "a resubmission is not a discovery"
    assert second["already_known"] == [
        {"title": "Bearing housing cracks after 800 hours",
         "claim_id": claim, "corroborated": True},
    ]
    # The second page is still evidence: reported → corroborated.
    sources = store.execute(
        "SELECT COUNT(*) FROM evidence WHERE claim_id = ?", (claim,)
    ).fetchone()[0]
    assert sources == 2, "a second page saying it is exactly the point"
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1


def test_the_same_page_twice_adds_nothing(store):
    _submit(store, rationale=GOOD)
    again = _submit(store, rationale=GOOD)
    assert again["already_known"][0]["corroborated"] is False, (
        "the same source and quote must not count as corroboration"
    )
    assert store.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1


def test_the_reader_is_told_what_was_new_and_what_was_known(store):
    _submit(store, rationale=GOOD)
    again = _submit(store, rationale=GOOD, source_url="https://other.example.com/x")
    assert "1 finding(s) already known" in again["summary"]
    assert "with a new source" in again["summary"]


def test_a_known_claim_still_counts_toward_its_domain(store):
    """The gap map answers for the store, not for the batch."""
    _submit(store, rationale=GOOD)
    again = _submit(store, rationale=GOOD, source_url="https://other.example.com/x")
    assert again["gaps"]["domains_covered"] == ["mech"]
    assert again["gaps"]["domains_empty"] == []


# ── the documents that teach the loop ──────────────────────────────────────


def test_the_brief_makes_the_loop_explicit(store):
    brief = AgentResearcher().brief(plan_task(store, _subject(store), "tools"))
    assert "did not establish" in brief, (
        "the brief must say that the submit answer names what is missing"
    )
    assert "never re-run a seed" in brief, (
        "seed re-rolls are the failure the loop exists to prevent"
    )
    assert "nothing missing" in brief, "the stop condition must be stated"


def test_the_skill_teaches_step_five_is_not_the_end(store):
    body = agentskill.render(store) or ""
    assert "Step 5 is not the end" in body
    assert "stop signal" in body
    assert "brief's seeds" in body
