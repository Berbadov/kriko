import sqlite3
import pytest
from knowledge.ledger import db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "ledger.db")


def _doc(conn, text="EA888 timing chain stretch", url="https://x.test/a"):
    return db.insert_document(conn, url=url, source_type="page", raw_text=text)


def test_insert_document_dedups_by_text_hash(conn):
    a = _doc(conn)
    b = _doc(conn, url="https://different.test/b")  # same text
    assert a == b
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_documents_and_evidence_are_append_only(conn):
    doc_id = _doc(conn)
    ev_id = db.insert_evidence(
        conn, doc_id=doc_id,
        claim={"title": "t", "domain": "engine", "severity": "medium",
               "rationale": "r", "inspection_advice": "i", "quote": "q",
               "engine_or_variant_hint": "EA888", "quote_grounded": True},
        span_start=0, span_end=5, extractor_version=2,
    )
    for stmt in (
        "DELETE FROM documents", "UPDATE documents SET url='x'",
        "DELETE FROM evidence", f"UPDATE evidence SET title='x' WHERE id={ev_id}",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(stmt)


def test_low_value_flag_lives_outside_evidence(conn):
    doc_id = _doc(conn)
    ev_id = db.insert_evidence(
        conn, doc_id=doc_id,
        claim={"title": "warning light", "domain": "general", "severity": "low",
               "rationale": "", "inspection_advice": "", "quote": "",
               "engine_or_variant_hint": None, "quote_grounded": False},
        span_start=None, span_end=None, extractor_version=2,
    )
    db.flag_low_value(conn, ev_id, "warning-light pattern")
    row = conn.execute(
        "SELECT reason FROM evidence_flags WHERE evidence_id=?", (ev_id,)
    ).fetchone()
    assert row["reason"] == "warning-light pattern"


def test_connect_is_idempotent(tmp_path):
    p = tmp_path / "l.db"
    db.connect(p).close()
    db.connect(p).close()  # schema re-run must not fail
