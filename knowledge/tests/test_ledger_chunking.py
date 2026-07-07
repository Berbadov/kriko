from knowledge.ledger.chunking import (
    CHUNK_CHARS, CHUNK_OVERLAP, chunk_has_signal, chunk_text,
)


def test_chunks_cover_full_text_with_overlap():
    text = "x" * 10_000
    chunks = chunk_text(text)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    for a, b in zip(chunks, chunks[1:]):
        assert b.start == a.end - CHUNK_OVERLAP  # overlap preserved
    assert all(len(c.text) <= CHUNK_CHARS for c in chunks)


def test_short_text_is_single_chunk():
    assert len(chunk_text("short")) == 1


def test_signal_gate_turkish_english_and_codes():
    assert chunk_has_signal("bu motorda kronik termostat arıza var")   # TR lexicon
    assert chunk_has_signal("the timing chain is a known failure")     # EN lexicon
    assert chunk_has_signal("the EA888 uses a different tensioner")    # code token
    assert not chunk_has_signal("today we unbox the new infotainment") # filler
