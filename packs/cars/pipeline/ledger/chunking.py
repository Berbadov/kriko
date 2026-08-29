"""Cars' chunk gate: the engine's failure lexicon plus car code tokens.

Chunking itself is generic and lives in ``kriko.ledger.chunking``. The only
car-shaped part is what counts as signal — an engine or gearbox code makes a
chunk worth extracting even when it names no failure word. ``code_tokens`` is
catalog-derived, so a new part is covered the moment its stub exists.
"""

from kriko.ledger.chunking import (  # noqa: F401 — re-exported for callers
    CHUNK_CHARS,
    CHUNK_OVERLAP,
    Chunk,
    chunk_text,
)
from kriko.ledger.chunking import chunk_has_signal as _engine_has_signal
from packs.cars.pipeline.stoplists import CAR_FAILURE_TERMS, code_tokens


def chunk_has_signal(text: str) -> bool:
    """Whether this chunk is worth spending extraction tokens on."""
    if _engine_has_signal(text, signal_terms=CAR_FAILURE_TERMS):
        return True
    return bool(code_tokens(text))
