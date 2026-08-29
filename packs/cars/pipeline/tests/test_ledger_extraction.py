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

    # verify chunk is marked as done
    from packs.cars.pipeline.ledger.chunking import chunk_text
    n_chunks = len(list(chunk_text(text)))
    done_count = conn.execute("SELECT COUNT(*) FROM extraction_done").fetchone()[0]
    assert done_count == n_chunks  # all chunks settled

    # second run: fully cached, zero LLM calls, zero new evidence
    added = extraction.extract_document(conn, doc_id, budget)
    assert added == 0
    assert len(calls) == 1  # no new calls (same as before, cached)
