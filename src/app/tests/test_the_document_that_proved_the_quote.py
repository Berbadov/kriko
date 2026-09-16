"""B120 — keeping the text a quote was checked against.

*"Are we skipping document making?"* — we were. An agent submits
`document_text`; `app/findings.py` used it for exactly one thing,
`is_grounded(document, quote)`, and then dropped it. What reached the store was
`sources` (url, domain, `retrieved_at`) and `evidence` (quote, stance). There is
no `documents` table in `src/kriko/store/schema.sql`, and the one in
`src/kriko/ledger/db.py` is build-time machinery the live path never touches.

The evidence chain is this product's one hard guarantee, and that made it a
guarantee which could be checked exactly once, against text nobody kept. Now the
document is kept in `app.sqlite` — interface state, never the engine's store, so
a page this installation happened to read cannot change a pack's
`content_digest` — and the check can be made again with no network and no model.

The tests below are about the three things that were impossible: repeating the
check, telling "never fetched" from "fetched and gone", and doing either after
the page has changed.
"""

import pytest

from app import findings as findings_mod
from app.findings import accept_findings, log_submission, regrounded
from app.web import state
from kriko.store.db import connect

PAGE = (
    "Owners report that the timing chain kit on this engine is unobtainable in "
    "some markets. Several have waited months for the part."
)
QUOTE = "the timing chain kit on this engine is unobtainable in some markets"


def _finding(**over) -> dict:
    base = {
        "title": "Timing chain kit unobtainable",
        "domain": "engine",
        "severity": "high",
        "quote": QUOTE,
        "document_text": PAGE,
        "source_url": "https://forum.example/thread/1",
        "component": "timing chain kit",
    }
    return {**base, **over}


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Thing s1')"
    )
    conn.commit()
    return conn


def _accept(store, tmp_path, items: list[dict]) -> tuple[dict, list[dict]]:
    kept: list[dict] = []
    verdicts = accept_findings(store, "s1", "probe", items, retain=kept)
    store.commit()
    log_submission(
        tmp_path / "app.sqlite",
        door="job",
        subject_id="s1",
        pack_id="probe",
        verdicts=verdicts,
        documents=kept,
    )
    return verdicts, kept


def test_the_text_a_quote_was_proved_against_is_kept(store, tmp_path):
    verdicts, kept = _accept(store, tmp_path, [_finding()])
    assert len(verdicts["accepted"]) == 1
    app_conn = state.connect(tmp_path / "app.sqlite")
    document = state.document_for(app_conn, kept[0]["source_id"])
    assert document["text"] == PAGE
    assert document["url"] == "https://forum.example/thread/1"


def test_the_check_can_be_made_again_with_no_network(store, tmp_path):
    """The point of keeping it. `app/factcheck.py` goes out to the web and asks
    whether the page still says it; this asks the narrower question — does the
    quote appear in the text this install actually read — which needs no
    permission, no timeout and no user agent."""
    verdicts, _ = _accept(store, tmp_path, [_finding()])
    claim_id = verdicts["accepted"][0]["claim_id"]
    (row,) = regrounded(store, tmp_path / "app.sqlite", "probe", claim_id)
    assert row["verdict"] == "grounded"
    assert row["quote"] == QUOTE


def test_a_page_that_changed_under_a_claim_is_detectable(store, tmp_path):
    """A later read of the same URL replaces the copy, and the claim's quote is
    then checked against what the page says *now*.

    This is the situation the old code could not represent at all: the evidence
    said one thing, the page said another, and nothing anywhere held both."""
    verdicts, kept = _accept(store, tmp_path, [_finding()])
    claim_id = verdicts["accepted"][0]["claim_id"]
    app_conn = state.connect(tmp_path / "app.sqlite")
    state.retain_documents(
        app_conn,
        [{
            "source_id": kept[0]["source_id"],
            "pack_id": "probe",
            "url": "https://forum.example/thread/1",
            "text": "This thread has been removed by a moderator.",
        }],
    )
    (row,) = regrounded(store, tmp_path / "app.sqlite", "probe", claim_id)
    assert row["verdict"] == "ungrounded"


def test_a_source_nothing_ever_fetched_says_so(store, tmp_path):
    """B112's second enforcement, which was unimplementable as written.

    "A `source_url` that was never fetched is a fabrication with a plausible
    shape" needs something that knows which documents were fetched. Nothing
    did. `not_kept` is that answer, and it is deliberately not `ungrounded` —
    absence of the page is not evidence against the quote."""
    verdicts, _ = _accept(store, tmp_path, [_finding()])
    claim_id = verdicts["accepted"][0]["claim_id"]
    (row,) = regrounded(store, tmp_path / "unwritten.sqlite", "probe", claim_id)
    assert row["verdict"] == "not_kept"


def test_a_refused_finding_leaves_no_document_behind(store, tmp_path):
    """Only what was accepted is kept. A page that proved nothing is not
    evidence of anything, and keeping it would turn the bound into a budget
    spent on refusals."""
    _, kept = _accept(
        store,
        tmp_path,
        [_finding(quote="a sentence that is not on that page at all")],
    )
    assert kept == []
    app_conn = state.connect(tmp_path / "app.sqlite")
    assert state.documents_kept(app_conn)["documents"] == 0


def test_two_findings_from_one_page_keep_one_copy(store, tmp_path):
    """Both quotes come out of the same read, so a second copy answers no
    question the first cannot — and it is the cross-check that was impossible
    while neither was kept."""
    _accept(
        store,
        tmp_path,
        [
            _finding(),
            _finding(
                title="Owners wait months for the part",
                quote="Several have waited months for the part",
            ),
        ],
    )
    app_conn = state.connect(tmp_path / "app.sqlite")
    assert state.documents_kept(app_conn)["documents"] == 1


def test_what_is_kept_is_bounded(tmp_path, monkeypatch):
    """A local database that grows with every page ever read is a defect with a
    long fuse. The bound is rows, newest first."""
    monkeypatch.setattr(state, "DOCUMENTS_KEPT", 3)
    conn = state.connect(tmp_path / "app.sqlite")
    for index in range(10):
        state.retain_documents(
            conn,
            [{"source_id": f"s{index}", "pack_id": "p", "url": "u", "text": "x"}],
        )
    assert state.documents_kept(conn)["documents"] == 3
    assert state.document_for(conn, "s9") is not None
    assert state.document_for(conn, "s0") is None


def test_a_page_too_large_to_keep_is_recorded_as_fetched_rather_than_truncated(
    tmp_path, monkeypatch
):
    """Half a page would re-check as `ungrounded` for a quote that was
    genuinely in the other half — one confident wrong answer, which is worse
    than the honest "this was read and is not kept"."""
    monkeypatch.setattr(state, "MAX_DOCUMENT_CHARS", 50)
    conn = state.connect(tmp_path / "app.sqlite")
    state.retain_documents(
        conn, [{"source_id": "s1", "pack_id": "p", "url": "u", "text": "y" * 500}]
    )
    row = state.document_for(conn, "s1")
    assert row["text"] == ""
    assert row["chars"] == 500


def test_the_document_never_reaches_the_engines_store(store, tmp_path):
    """The load-bearing decision, and the reason this is not in
    `kriko/store/schema.sql`: a page one installation happened to read must not
    change a pack's `content_digest`, or two readers who researched the same
    subject would disagree about whether an update is a republish."""
    _accept(store, tmp_path, [_finding()])
    tables = {
        row[0]
        for row in store.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "documents" not in tables


def test_the_verdicts_handed_back_do_not_carry_the_page(store, tmp_path):
    """The submitting agent gets its verdicts, not its own page text echoed at
    it — which is why `retain` is a collecting list rather than another key in
    the return value."""
    verdicts, _ = _accept(store, tmp_path, [_finding()])
    assert "documents" not in verdicts
    assert PAGE not in str(verdicts)


def test_bookkeeping_is_never_why_a_finding_is_lost(store, tmp_path, monkeypatch):
    """`log_submission` is silent on failure for a reason that applies here
    too: the claims are already written, and an unwritable document store must
    not undo them."""
    def explode(*args, **kwargs):
        raise RuntimeError("the disk is gone")

    monkeypatch.setattr(state, "retain_documents", explode)
    verdicts, _ = _accept(store, tmp_path, [_finding()])
    assert len(verdicts["accepted"]) == 1


def test_regrounding_a_claim_that_has_no_evidence_is_empty_not_an_error(
    store, tmp_path
):
    assert regrounded(store, tmp_path / "app.sqlite", "probe", "no-such-claim") == []


def test_the_module_says_where_the_document_lives(store):
    """The absence of a recorded decision is what made B120 a defect rather
    than a trade-off. The next reader gets the reasoning in the code."""
    assert "content_digest" in state.SCHEMA
    assert "B120" in findings_mod.regrounded.__doc__
