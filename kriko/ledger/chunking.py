"""Full-document chunking + the deterministic pre-LLM chunk gate.

Replaces extract.py's doc.text[:6000] cap: the WHOLE document is chunked, but
a chunk only reaches the extraction LLM if it contains failure-lexicon signal
or an engine/transmission code token — transcripts are mostly filler, and this
gate is where 50-70% of extraction tokens are saved at zero cost."""

from collections.abc import Iterable
from dataclasses import dataclass

CHUNK_CHARS = 4000
CHUNK_OVERLAP = 400

# Substring stems, not whole words: Turkish agglutination means "bozul" must
# match bozuldu/bozulması/bozulan. Lowercased match. Genuinely closed
# vocabulary (fixed engineering/failure words), so a constant is allowed per
# CLAUDE.md's scalability-principle exception.
FAILURE_LEXICON: frozenset[str] = frozenset(
    {
        # Turkish
        "arıza",
        "ariza",
        "sorun",
        "kronik",
        "bozul",
        "patla",
        "sızdır",
        "sizdir",
        "kaçır",
        "kacir",
        "değiş",
        "degis",
        "yaptırdım",
        "yaptirdim",
        "garanti",
        # English
        "fail",
        "fault",
        "problem",
        "issue",
        "broke",
        "broken",
        "defect",
        "recall",
        "leak",
        "wear",
        "worn",
        "replace",
        "repair",
        "chronic",
        "stretch",
        "rattle",
        "shudder",
        "judder",
        "misfire",
        "clog",
    }
)


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int
    text: str


def chunk_text(text: str) -> list[Chunk]:
    step = CHUNK_CHARS - CHUNK_OVERLAP
    chunks: list[Chunk] = []
    i, start = 0, 0
    while start < len(text) or not chunks:
        end = min(start + CHUNK_CHARS, len(text))
        chunks.append(Chunk(index=i, start=start, end=end, text=text[start:end]))
        if end == len(text):
            break
        start += step
        i += 1
    return chunks


def chunk_has_signal(text: str, signal_terms: Iterable[str] = ()) -> bool:
    """Return whether text merits extraction.

    The default vocabulary is deliberately category-neutral. A pack may add
    its own tokens (for example, identifiers declared in its data) without
    making the ledger know that vocabulary.
    """
    lowered = text.lower()
    return any(stem in lowered for stem in FAILURE_LEXICON) or any(
        term.lower() in lowered for term in signal_terms
    )
