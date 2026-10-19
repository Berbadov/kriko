import pytest
from kriko.ledger import costs, db
from packs.cars.pipeline.ledger import extraction


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def _page(conn, text, hint="dq381"):
    return db.insert_document(conn, url="https://x.test/a", source_type="page",
                              raw_text=text, target_hint=hint)


def test_extracts_only_signal_chunks_and_caches(conn, monkeypatch):
    calls = []
    def fake_extract(text):
        calls.append(text)
        return [{"title": "DQ200 accumulator failure", "domain": "transmission",
                 "severity": "high", "rationale": "hydraulic pressure loss",
                 "inspection_advice": "scan for P189C", "quote": text[:30],
                 "engine_or_variant_hint": "DQ200", "quote_grounded": True}]
    monkeypatch.setattr(extraction, "extract_grounded", fake_extract)

    filler = "unboxing the infotainment today " * 200        # no signal
    signal = " the DQ200 accumulator is a chronic failure " * 100
    doc_id = _page(conn, filler + signal)
    budget = costs.Budget()

    added = extraction.extract_document(conn, doc_id, budget)
    assert added >= 1
    n_first = len(calls)
    assert 0 < n_first  # signal chunks called
    # filler-only leading chunk was skipped: fewer calls than total chunks
    from packs.cars.pipeline.ledger.chunking import chunk_text
    assert n_first < len(chunk_text(filler + signal))

    # second run: fully cached, zero LLM calls, zero new evidence
    assert extraction.extract_document(conn, doc_id, budget) == 0
    assert len(calls) == n_first


def test_span_mapped_to_full_document(conn, monkeypatch):
    text = ("padding " * 50) + "the EA888 timing chain stretches early" + (" tail" * 50)
    quote = "EA888 timing chain stretches"
    monkeypatch.setattr(extraction, "extract_grounded", lambda t: [{
        "title": "EA888 chain stretch", "domain": "engine", "severity": "high",
        "rationale": "known failure", "inspection_advice": "listen cold start",
        "quote": quote, "engine_or_variant_hint": "EA888", "quote_grounded": True}])
    doc_id = _page(conn, text)
    extraction.extract_document(conn, doc_id, costs.Budget())
    row = conn.execute("SELECT span_start, span_end FROM evidence").fetchone()
    assert row["span_start"] == text.find(quote)
    assert row["span_end"] == text.find(quote) + len(quote)


def test_deterministic_low_value_flagging(conn, monkeypatch):
    monkeypatch.setattr(extraction, "extract_grounded", lambda t: [{
        "title": "ABS warning light comes on", "domain": "electrical",
        "severity": "low", "rationale": "dashboard warning light appears",
        "inspection_advice": "", "quote": "arıza lambası", "quote_grounded": True,
        "engine_or_variant_hint": None}])
    doc_id = _page(conn, "kronik arıza lambası sorunu " * 100)
    extraction.extract_document(conn, doc_id, costs.Budget())
    assert conn.execute("SELECT COUNT(*) FROM evidence_flags").fetchone()[0] == 1


def test_budget_abort_leaves_ledger_resumable(conn, monkeypatch):
    monkeypatch.setattr(extraction, "extract_grounded", lambda t: [])
    # leading filler chunk (settled free, cached) then signal chunks (charged)
    text = ("unboxing video intro " * 300) + ("chronic failure text " * 2000)
    doc_id = _page(conn, text)
    with pytest.raises(costs.BudgetExceeded):
        extraction.extract_document(conn, doc_id, costs.Budget(max_usd=0.000001))
    done = conn.execute("SELECT COUNT(*) FROM extraction_done").fetchone()[0]
    assert done >= 1  # settled chunks stay cached; rerun resumes, not restarts


def test_malformed_claims_do_not_break_chunk_cache(conn, monkeypatch):
    """A lost claim is recorded, and the chunk stays pending so it is retried.

    This used to assert the opposite — that the chunk was marked done anyway —
    which was the defect: the loss was permanent *and* invisible, because
    `extract_document` returns a success count and the run's screen said the
    same thing whether it kept forty of forty or forty of forty-three. The
    assertion moved to the new intent (`CLAUDE.md`: "a test that asserts retired
    behaviour is rewritten to assert the new intent").
    """
    calls = []
    def fake_extract(text):
        calls.append(text)
        return [
            # valid claim
            {"title": "DQ200 accumulator failure", "domain": "transmission",
             "severity": "high", "rationale": "hydraulic pressure loss",
             "inspection_advice": "scan for P189C", "quote": text[:30],
             "engine_or_variant_hint": "DQ200", "quote_grounded": True},
            # malformed claim (missing domain and severity)
            {"title": "missing fields"}
        ]
    monkeypatch.setattr(extraction, "extract_grounded", fake_extract)

    # use short text to ensure only 1 chunk
    text = "the DQ200 accumulator is a chronic failure " * 50
    doc_id = _page(conn, text)
    budget = costs.Budget()

    # first run: processes both claims, but only valid one is inserted
    added = extraction.extract_document(conn, doc_id, budget)
    assert added == 1  # only valid claim inserted
    assert len(calls) >= 1  # extract_grounded called at least once

    # The chunk is *not* settled: it lost a claim, so the next pass retries it.
    done_count = conn.execute("SELECT COUNT(*) FROM extraction_done").fetchone()[0]
    assert done_count == 0
    lost = extraction.failures(conn)
    assert [one["attempts"] for one in lost] == [1]
    # The first missing field the insert reached. `domain` before `severity`
    # because that is the column order in the statement, and the point of the
    # assertion is that the *reason* is recorded at all.
    assert "domain" in lost[0]["error"]

    # The valid claim is not written twice by the retry: `insert_evidence` is
    # idempotent on (doc_id, quote, title), which is what makes the retry safe.
    added = extraction.extract_document(conn, doc_id, budget)
    assert added == 1
    stored = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE title = 'DQ200 accumulator failure'"
    ).fetchone()[0]
    assert stored == 1
    assert extraction.failures(conn)[0]["attempts"] == 2

    # And after the cap it is settled, so a claim that can never be written
    # stops being bought from the provider — with the reason still on record.
    extraction.extract_document(conn, doc_id, budget)
    assert conn.execute("SELECT COUNT(*) FROM extraction_done").fetchone()[0] == 1
    assert extraction.failures(conn)[0]["attempts"] == 3


def test_low_value_reason_comes_from_pack_rows_not_python_constants():
    """The gate's vocabulary is data the pack ships, not an engine constant.

    A warning-light claim is rejected because packs/cars/vocabulary/gates.yaml
    declares that pattern under `noise` — not because a frozenset in
    stoplists.py happens to list it. The reason string is the rule kind, which
    is what makes a rejection traceable back to the row that caused it.
    """
    from packs.cars.pipeline.ledger.extraction import _low_value_reason

    assert _low_value_reason({"title": "ABS warning light comes on",
                              "rationale": ""}) == "noise"
    assert _low_value_reason({"title": "DQ381 mechatronics unit fails at 120000 km",
                              "rationale": "Known weak point."}) is None


def test_vocabulary_fails_open_on_mis_shaped_gates_file(tmp_path, monkeypatch):
    """A gates.yaml that parses but is shaped wrong must gate nothing.

    ``_vocabulary``'s own docstring promises "a missing or unreadable file
    gates nothing" — that promise has to hold for YAML that parses fine but
    has the wrong shape too (a list entry with no ``pattern`` key, say), not
    just for a missing file or invalid YAML syntax. This exercises the real
    function against a real file rather than ``vocabulary_from_rows``
    directly, because the bug this guards against lives in the row-shaping
    step between the parse and the compile.
    """
    from kriko.gates import GateVocabulary
    from packs.cars.pipeline.ledger import extraction

    vocab_dir = tmp_path / "vocabulary"
    vocab_dir.mkdir()
    (vocab_dir / "gates.yaml").write_text(
        "noise:\n  - pattern_typo: not a pattern key\n"
    , encoding="utf-8")
    monkeypatch.setattr(extraction, "PACK_ROOT", tmp_path)

    extraction._vocabulary.cache_clear()
    try:
        assert extraction._vocabulary() == GateVocabulary()
    finally:
        extraction._vocabulary.cache_clear()
