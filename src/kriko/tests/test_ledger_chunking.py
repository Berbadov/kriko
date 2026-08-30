"""kriko.ledger.chunking — generic chunking and the pre-LLM signal gate."""

from kriko.ledger.chunking import (
    CHUNK_CHARS, CHUNK_OVERLAP, chunk_has_signal, chunk_text,
)


def test_chunks_overlap_and_cover_the_whole_text():
    text = "x" * (CHUNK_CHARS * 2)
    chunks = chunk_text(text)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)
    assert chunks[1].start == CHUNK_CHARS - CHUNK_OVERLAP


def test_short_text_is_one_chunk():
    assert len(chunk_text("short")) == 1


def test_empty_text_still_yields_one_chunk():
    assert len(chunk_text("")) == 1


def test_the_default_lexicon_is_category_neutral():
    """A failure word any category shares is signal; a car word is not.

    The engine may not know what a misfire is — that is pack vocabulary, and
    it reaches the gate through signal_terms rather than through a constant
    here. Guards the G6 invariant at the one place it silently regressed.
    """
    assert chunk_has_signal("this part has a known failure")
    assert chunk_has_signal("bu parçada kronik arıza var")
    assert not chunk_has_signal("the engine has a misfire")
    assert chunk_has_signal("the engine has a misfire", signal_terms={"misfire"})


def test_filler_is_not_signal():
    assert not chunk_has_signal("today we unbox the new infotainment")
