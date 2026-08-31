"""Pack-declared claim gates, without category-specific judgement."""

import pytest

from kriko.gates import gate_reason, load_gates
from kriko.store import packstore
from kriko.store.db import connect

VOCAB = [
    ("covered", "battery contact", ""),
    ("generic", "wear and tear is normal", ""),
    ("ambiguous", "chuck runout", ""),
    ("noise", r"\bindicator\s+light\b", ""),
    ("specificity", r"\b[A-Za-z]{1,4}\d[A-Za-z0-9]{0,3}\b", ""),
    ("exempt", "recall", ""),
]


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "s.sqlite")
    with conn:
        packstore.write_pack_row(
            conn, pack_id="p", name="P", version="1", content_digest="x"
        )
        for row in VOCAB:
            conn.execute("INSERT INTO gate_terms VALUES (?,?,?,?)", ("p", *row))
    yield conn
    conn.close()


def test_literal_and_regex_rules_reject(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Battery contact wear", vocab) == "covered"
    assert gate_reason("Wear and tear is normal", vocab) == "generic"
    assert gate_reason("Battery indicator light", vocab) == "noise"


def test_ambiguous_term_survives_with_specificity(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Chuck runout in DHP484 drills", vocab) is None
    assert gate_reason("Chuck runout is worth watching", vocab) == "ambiguous"


def test_unmatched_text_is_kept(store):
    assert (
        gate_reason("Motor unit fails above 1,200 charge cycles", load_gates(store, "p"))
        is None
    )


def test_exempt_waives_the_covered_rejection(store):
    """An official recall is authoritative even when it names a covered part."""
    vocab = load_gates(store, "p")
    assert gate_reason("Recall: battery contact replacement", vocab) is None


def test_exempt_does_not_waive_a_noise_rejection(store):
    """`exempt` narrows to `covered` only — it must not blanket-waive every gate.

    A warning-light title stays refused even when the text also mentions a
    recall: the recall carve-out is about routine-inspection vocabulary
    describing an authoritative fix, not a licence for any other low-value
    shape to ride along with it.
    """
    vocab = load_gates(store, "p")
    assert (
        gate_reason("Battery indicator light illuminates (recall)", vocab) == "noise"
    )


def test_subject_lets_a_rationale_only_covered_term_survive(store):
    """`covered` judges what the claim is about, not everything it mentions.

    A rationale explaining a chronic's mechanism may use covered vocabulary
    ("battery contact") without the claim itself being a routine
    contact-wear item — passing `subject` scopes the covered check to the
    title; omitting it scans the whole blob and still rejects.
    """
    vocab = load_gates(store, "p")
    # No specificity anchor in either the title or the rationale here — the
    # point under test is subject-scoping, not the anchor escape, so neither
    # must accidentally trip it.
    title = "Motor housing crack"
    rationale = "Debris from worn battery contact material can contaminate the unit."
    text = f"{title} {rationale}"
    assert gate_reason(text, vocab, subject=title) is None
    assert gate_reason(text, vocab) == "covered"


def test_noise_is_scoped_to_subject_and_waived_by_specificity(store):
    """A rationale mentioning an indicator light must not sink a specific chronic.

    The bug: `noise` used to match `title + rationale` with no escape at
    all, so a claim like "DHP484 motor housing crack" got refused
    because its rationale happened to explain the failure's indicator-light
    symptom. `noise` now reads `subject` only, and — like `covered` — keeps
    the specificity escape.
    """
    vocab = load_gates(store, "p")
    title = "DHP484 motor housing crack"
    rationale = "This causes the battery indicator light to illuminate under load."
    text = f"{title} {rationale}"
    assert gate_reason(text, vocab, subject=title) is None
    # A title that itself names the indicator-light shape, with no anchor,
    # is still refused — the escape is for the rationale riding along, not a
    # blanket waiver of the rule.
    assert gate_reason("Battery indicator light", vocab,
                        subject="Battery indicator light") == "noise"


def test_anchor_waives_generic_and_ambiguous_like_an_in_text_signal(store):
    """A caller-supplied component anchor rescues generic/ambiguous wording.

    Mirrors what `structural_reasons`' own specificity escape already does —
    an agent that names a `component`/`component_hint` should not need to
    also spell the identifier out in prose for `gate_reason` to accept it.
    """
    vocab = load_gates(store, "p")
    text = "Wear and tear is normal"
    assert gate_reason(text, vocab) == "generic"
    assert gate_reason(text, vocab, has_anchor=True) is None

    ambiguous_text = "Chuck runout is worth watching"
    assert gate_reason(ambiguous_text, vocab) == "ambiguous"
    assert gate_reason(ambiguous_text, vocab, has_anchor=True) is None


def test_missing_pack_vocabulary_fails_open(tmp_path):
    conn = connect(tmp_path / "s.sqlite")
    with conn:
        packstore.write_pack_row(
            conn, pack_id="q", name="Q", version="1", content_digest="x"
        )
    assert gate_reason("anything at all", load_gates(conn, "q")) is None
    conn.close()


def test_bad_regex_does_not_disable_literal_rules(tmp_path):
    conn = connect(tmp_path / "s.sqlite")
    with conn:
        packstore.write_pack_row(
            conn, pack_id="r", name="R", version="1", content_digest="x"
        )
        conn.execute(
            "INSERT INTO gate_terms VALUES (?,?,?,?)", ("r", "noise", "[unclosed", "")
        )
        conn.execute(
            "INSERT INTO gate_terms VALUES (?,?,?,?)",
            ("r", "generic", "wear and tear is normal", ""),
        )
    assert gate_reason("Wear and tear is normal", load_gates(conn, "r")) == "generic"
    conn.close()


from kriko.gates import GateVocabulary, structural_reasons


def test_undeclared_limits_gate_nothing():
    """Fail open: a pack that declares no limits gets no structural rejections.

    CLAUDE.md's automation principle — where a value cannot be derived, emit
    nothing rather than guess. A pack author who has not thought about title
    length must not have the engine's opinion imposed on them.
    """
    assert structural_reasons("x", "y", GateVocabulary()) == []


def test_a_title_over_the_declared_limit_is_rejected():
    vocab = GateVocabulary(max_title_chars=20)
    assert structural_reasons("x" * 21, "", vocab) != []
    assert structural_reasons("x" * 20, "", vocab) == []


def test_a_rationale_under_the_declared_minimum_is_rejected():
    vocab = GateVocabulary(min_rationale_chars=30)
    assert structural_reasons("a title", "too short", vocab) != []
    assert structural_reasons("a title", "y" * 30, vocab) == []


def test_text_with_no_specificity_anchor_is_rejected_when_patterns_exist():
    """A pack that declares what 'specific' looks like gets the anchor rule.

    A pack that declares no specificity patterns has no way to express the
    rule, so it does not get it — again, fail open rather than guess.
    """
    vocab = GateVocabulary(specificity_patterns=_compiled(r"\bmk\d\b"))
    assert structural_reasons("a vague problem", "", vocab) != []
    assert structural_reasons("mk4 fails", "", vocab) == []
    assert structural_reasons("a vague problem", "", vocab, has_anchor=True) == []
    assert structural_reasons("a vague problem", "", GateVocabulary()) == []


def _compiled(pattern: str):
    import re
    return (re.compile(pattern, re.IGNORECASE),)
