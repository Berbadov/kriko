"""A claim that cannot be written is recorded and retried, not printed and lost.

`extract_document` caught `Exception` per claim, printed one line, and marked the
chunk `extraction_done` regardless. So the loss was permanent *and* invisible:
the function returns a success count, and the run's own screen said the same
thing whether it had kept forty claims out of forty or forty out of forty-three.

Two properties are pinned here, because the retry depends on both:
the failure is durable and its attempt count grows, and a chunk that is retried
does not write its already-stored claims twice.
"""

import pytest

from kriko.ledger import db, extraction
from kriko.ledger.costs import Budget

SENTENCE = ("The timing chain on this engine is a known problem: owners report "
            "stretch and wear after 60,000 miles, and the repair is expensive.")


def _document(conn, text=SENTENCE):
    return db.insert_document(conn, url="https://x.test/a", source_type="page",
                              raw_text=text)


def _claim(title="Timing chain stretch", quote=SENTENCE, **over):
    base = {"title": title, "domain": "mechanical", "severity": "high",
            "quote": quote, "quote_grounded": True, "rationale": "r"}
    return base | over


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "ledger.sqlite")
    yield connection
    connection.close()


def test_a_good_claim_is_stored_once(conn):
    doc = _document(conn)
    added = extraction.extract_document(
        conn, doc, Budget(), extractor=lambda _text: [_claim()])
    assert added == 1
    assert conn.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
    assert extraction.failures(conn) == []


def test_a_claim_that_cannot_be_written_is_recorded(conn):
    """`severity` missing is the shape of a real extractor slip."""
    doc = _document(conn)
    broken = _claim()
    del broken["severity"]
    added = extraction.extract_document(
        conn, doc, Budget(), extractor=lambda _text: [broken])
    assert added == 0
    lost = extraction.failures(conn)
    assert len(lost) == 1
    assert lost[0]["attempts"] == 1
    assert "severity" in lost[0]["error"]


def test_a_lost_claim_leaves_the_chunk_pending_for_the_next_pass(conn):
    doc = _document(conn)
    broken = _claim()
    del broken["severity"]
    extraction.extract_document(conn, doc, Budget(), extractor=lambda _text: [broken])
    assert conn.execute("SELECT count(*) FROM extraction_done").fetchone()[0] == 0

    # The second pass sees the same chunk and tries again.
    extraction.extract_document(conn, doc, Budget(), extractor=lambda _text: [broken])
    assert extraction.failures(conn)[0]["attempts"] == 2


def test_a_chunk_is_given_up_on_after_the_attempt_cap(conn):
    """A claim that always fails must stop being bought from the provider."""
    doc = _document(conn)
    broken = _claim()
    del broken["severity"]
    for _ in range(extraction.MAX_CHUNK_ATTEMPTS):
        extraction.extract_document(conn, doc, Budget(), extractor=lambda _text: [broken])
    assert conn.execute("SELECT count(*) FROM extraction_done").fetchone()[0] == 1


def test_a_retried_chunk_does_not_double_the_claims_it_already_stored(conn):
    """Two claims, one of which fails: the good one must not be written twice.

    Chunks overlap by 400 characters as well (`chunking.CHUNK_OVERLAP`), so the
    same passage legitimately reaches the extractor twice in one pass. Both
    paths are why `insert_evidence` is idempotent on `(doc_id, quote, title)`.
    """
    doc = _document(conn)
    broken = _claim(title="Second", quote=SENTENCE)
    del broken["severity"]

    extraction.extract_document(
        conn, doc, Budget(), extractor=lambda _text: [_claim(), broken])
    extraction.extract_document(
        conn, doc, Budget(), extractor=lambda _text: [_claim(), broken])

    stored = conn.execute(
        "SELECT count(*) FROM evidence WHERE title='Timing chain stretch'"
    ).fetchone()[0]
    assert stored == 1


def test_the_same_quote_under_two_titles_is_two_claims(conn):
    """The key is narrow on purpose: one sentence can support two failures."""
    doc = _document(conn)
    extraction.extract_document(
        conn, doc, Budget(),
        extractor=lambda _text: [_claim(title="Timing chain stretch"),
                                 _claim(title="Timing chain wear")])
    assert conn.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2
