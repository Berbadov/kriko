import sqlite3
import pytest
from kriko.ledger import db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "ledger.db")


def _doc(conn, text="Keyless chuck bearing wear on the DHP484", url="https://x.test/a"):
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
        claim={"title": "t", "domain": "mechanical", "severity": "medium",
               "rationale": "r", "inspection_advice": "i", "quote": "q",
               "component_hint": "keyless_chuck_13", "quote_grounded": True},
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


def test_insert_document_stores_published_at(conn):
    doc_id = db.insert_document(
        conn, url="https://x.test/a", source_type="page",
        raw_text="text", published_at="2021-05-03",
    )
    row = conn.execute(
        "SELECT published_at FROM documents WHERE id=?", (doc_id,)
    ).fetchone()
    assert row["published_at"] == "2021-05-03"


def test_insert_document_published_at_defaults_blank(conn):
    doc_id = _doc(conn)
    row = conn.execute(
        "SELECT published_at FROM documents WHERE id=?", (doc_id,)
    ).fetchone()
    assert row["published_at"] == ""


def test_connect_migrates_a_ledger_written_before_published_at_existed(tmp_path):
    """An older build's ledger has a `documents` table with no `published_at`
    column at all. `connect()` must add it (NOT NULL DEFAULT '') rather than
    fail the next insert against months of accumulated ledger data."""
    p = tmp_path / "old.db"
    old = sqlite3.connect(str(p))
    old.execute(
        "CREATE TABLE documents ("
        " id INTEGER PRIMARY KEY, url TEXT NOT NULL, source_type TEXT NOT NULL,"
        " site_or_channel TEXT NOT NULL DEFAULT '', lang TEXT NOT NULL DEFAULT '',"
        " target_hint TEXT NOT NULL DEFAULT '', raw_text TEXT NOT NULL,"
        " text_hash TEXT NOT NULL UNIQUE, fetched_at TEXT NOT NULL)"
    )
    old.execute(
        "INSERT INTO documents (url, source_type, raw_text, text_hash, fetched_at)"
        " VALUES ('https://x.test/old', 'page', 'old text', 'h1', 'then')"
    )
    old.commit()
    old.close()

    reconnected = db.connect(p)
    columns = {row[1] for row in reconnected.execute("PRAGMA table_info(documents)")}
    assert "published_at" in columns
    row = reconnected.execute(
        "SELECT published_at FROM documents WHERE url='https://x.test/old'"
    ).fetchone()
    assert row["published_at"] == ""  # old row backfilled honestly blank, not guessed

    new_id = db.insert_document(
        reconnected, url="https://x.test/new", source_type="page",
        raw_text="new text", published_at="2022-02-02",
    )
    row = reconnected.execute(
        "SELECT published_at FROM documents WHERE id=?", (new_id,)
    ).fetchone()
    assert row["published_at"] == "2022-02-02"
