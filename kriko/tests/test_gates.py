"""Pack-declared claim gates, without category-specific judgement."""

import pytest

from kriko.gates import gate_reason, load_gates
from kriko.store import packstore
from kriko.store.db import connect

VOCAB = [
    ("covered", "brake pad", ""),
    ("generic", "wear and tear is normal", ""),
    ("ambiguous", "oil consumption", ""),
    ("noise", r"\bwarning\s+light\b", ""),
    ("specificity", r"\b[A-Za-z]{1,4}\d[A-Za-z0-9]{0,3}\b", ""),
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
    assert gate_reason("Brake pad wear", vocab) == "covered"
    assert gate_reason("Wear and tear is normal", vocab) == "generic"
    assert gate_reason("ESP warning light", vocab) == "noise"


def test_ambiguous_term_survives_with_specificity(store):
    vocab = load_gates(store, "p")
    assert gate_reason("Oil consumption in EA211 engines", vocab) is None
    assert gate_reason("Oil consumption is worth watching", vocab) == "ambiguous"


def test_unmatched_text_is_kept(store):
    assert (
        gate_reason("Mechatronic unit fails above 120,000 km", load_gates(store, "p"))
        is None
    )


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
