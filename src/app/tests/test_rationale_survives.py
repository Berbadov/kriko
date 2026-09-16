"""`rationale is 0 chars`, three times over, on three good titles.

The reader's report, and it was never a model behaving badly. Two names for one
concept, bridged nowhere:

* `kriko.gates` measures `rationale`.
* `claim_text` stores `body`.
* `research.Finding` carries `body`, the paid plane's prompt asks for `body`,
  and `accept_findings` read `rationale`.

So the gate measured a field the paid plane never filled and refused everything
it produced — while an agent that *did* fill `rationale` passed the gate and had
its explanation dropped on the way into the store, landing a claim with a title
and nothing under it. Both directions broken, both looking like the model's
fault.
"""

import pytest

from app.findings import accept_findings, explanation, summarise
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

import textwrap

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

#: The pack's own bar, in the pack's own file. Nothing in the engine or the
#: interface names a number.
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


# ── the bridge ───────────────────────────────────────────────────────────

def test_an_explanation_written_as_body_is_no_longer_refused(store):
    """The paid plane's spelling. Every finding it produced was binned."""
    out = _submit(store, body=GOOD)
    assert out["accepted"], out["rejected"]


def test_an_explanation_written_as_rationale_reaches_the_store(store):
    """The agent plane's spelling. It passed the gate and vanished on the way in.

    The nastier of the two: nothing was refused, so nothing looked wrong, and
    the claim landed with a title and nothing under it.
    """
    out = _submit(store, rationale=GOOD)
    assert out["accepted"]
    body = store.execute("SELECT body FROM claim_text").fetchone()["body"]
    assert body == GOOD, "an accepted claim must keep the text it was judged on"


def test_the_stored_text_is_the_text_the_gate_measured(store):
    """Whichever name it arrived under, one string is judged and kept."""
    _submit(store, body=GOOD)
    body = store.execute("SELECT body FROM claim_text").fetchone()["body"]
    assert body == GOOD


def test_a_finding_with_neither_is_still_refused(store):
    """The bridge must not become a way past the bar."""
    out = _submit(store)
    assert not out["accepted"]
    assert "rationale is 0 chars" in out["rejected"][0]["reason"]


def test_explanation_prefers_the_gates_own_name_when_both_are_sent(store):
    assert explanation({"rationale": "a", "body": "b"}) == "a"
    assert explanation({"body": "b"}) == "b"
    assert explanation({}) == ""


# ── which refusals are worth another attempt ─────────────────────────────

def test_an_empty_explanation_is_marked_as_one_edit_from_being_kept(store):
    out = _submit(store)
    assert out["rejected"][0]["fix"] == "rationale"


def test_a_fabricated_quote_is_never_marked_repairable(store):
    """Asking again would be asking it to try harder at the thing it got wrong."""
    out = _submit(store, body=GOOD, quote="A sentence that is not in the page.")
    assert out["accepted"] == []
    assert out["rejected"][0].get("fix", "") == ""


# ── what the reader is told, rather than what the model is told ──────────

def test_the_reader_is_not_shown_the_models_error_message(store):
    out = _submit(store)
    assert "could not be explained" in out["summary"]
    assert "0 chars" not in out["summary"], "debug output in the reader's face"


def test_the_summary_counts_held_back_and_refused_apart():
    held = [{"title": "a", "reason": "rationale is 0 chars", "fix": "rationale"}]
    refused = [{"title": "b", "reason": "quote does not appear", "fix": ""}]
    said = summarise([{"title": "c"}], held + refused)
    assert "1 finding(s) kept" in said
    assert "1 could not be explained" in said
    assert "1 did not survive" in said


def test_a_clean_run_says_so_without_a_list_of_nothings():
    assert summarise([{"title": "a"}], []) == "1 finding(s) kept."


# ── the pack's number reaches the prompt ─────────────────────────────────

def test_the_extractor_is_told_the_minimum_before_it_writes(store):
    """It was only ever *checked*, after the work was done.

    A model asked for `body` in a list of seven keys writes a phrase. The gate
    wants two sentences. That gap was the entire yield of some runs, and no
    prompt anywhere mentioned it.
    """
    from kriko.research import plan_task

    task = plan_task(store, _subject(store), "tools")
    assert task.min_rationale_chars == 60
    assert "60 characters" in task.rationale_rule


def test_a_pack_declaring_no_minimum_still_gets_asked_for_sentences(store):
    from kriko.research.base import ResearchTask

    rule = ResearchTask(subject_id="s", subject_label="l", subject_kind="k",
                        pack_id="p").rationale_rule
    assert "plain sentences" in rule
    assert "characters" not in rule, "a number nobody declared is a number invented"
