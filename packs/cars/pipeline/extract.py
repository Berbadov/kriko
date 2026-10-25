"""Extraction layer — turns raw source text into structured CandidateClaims.

Uses langextract (packs.cars.pipeline.langextract_client) for grounded, few-shot
extraction over DeepSeek's OpenAI-compatible endpoint: each claim's quote is
aligned to an exact character span in the source text rather than trusted as a
self-reported string, closing a hallucination gap the old raw-JSON approach
left entirely to gate_support's separate LLM call. Accuracy of the *claim
itself* (is this really a known issue, does it belong to this variant) is
still the gate's job, not this layer's — grounding only verifies the quote is
real, not that the claim is true or correctly attributed.

**The whole document is read.** The old version passed `doc.text[:6000]`, so a
claim past that offset — a later post in a thread, the conclusion of a long
article, a fault mentioned at the end of a transcript — could never be
extracted. The document is now split into overlapping chunks (the engine's
generic `kriko.ledger.chunking`, the same one the ledger uses), the first and
last chunks are always read, and a middle chunk is read only when it carries a
deterministic failure signal. Claims repeated by the overlap are de-duplicated.

This module runs OFFLINE only — never on the /analyze request path.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kriko.ledger.chunking import chunk_text
from packs.cars.pipeline.ledger.chunking import chunk_has_signal
from packs.cars.pipeline.util.domains import normalize_domain
from packs.cars.pipeline.langextract_client import extract_grounded
from packs.cars.pipeline.sources.base import Document

#: A hard ceiling on LLM calls for one source. A two-hour transcript is around
#: 100k characters (25 chunks); past that the tail is dropped, and the tool
#: that prints the extraction says so. This is a cost bound, not a content
#: judgement: the ledger path has a real budget, while the pack builder does
#: not.
MAX_CHUNKS = 24


class CandidateClaim(BaseModel):
    title: str = Field(description="Short title of the reliability issue")
    domain: str = Field(description="Category: engine|transmission|electrical|emissions|fuel system|brakes|suspension|cooling|body|general")
    severity: Literal["high", "medium", "low"] = Field(description="Provisional: high|medium|low")
    rationale: str = Field(description="Plain-language explanation of the issue")
    inspection_advice: str = Field(description="What a buyer should check at viewing")
    quote: str = Field(description="VERBATIM span from the source text that supports this claim")
    engine_or_variant_hint: str | None = Field(
        default=None,
        description="Engine code or variant if mentioned (e.g. 'K9K', '1.5 dCi', 'H5H')"
    )
    quote_grounded: bool = Field(
        default=False,
        description="Whether langextract aligned `quote` to an exact character span in "
                     "the source text, vs. a fuzzy match or no match at all — new signal "
                     "the raw-JSON extractor never had (see packs/cars/pipeline/langextract_client.py)",
    )

    @field_validator("domain", mode="after")
    @classmethod
    def _coerce_domain(cls, v: str) -> str:
        # Coerce, never reject: an unmappable/malformed domain (multi-value
        # joins, invented synonyms) falls back to "general" rather than
        # failing validation and silently dropping the whole claim (see
        # packs/cars/pipeline/domains.py docstring).
        return normalize_domain(v)


def _claim_key(claim: CandidateClaim) -> str:
    """What makes two chunks' claims the same claim.

    The quote is the identity: overlapping chunks return the same verbatim
    span. Titles may be phrased differently around it, so they are not part of
    the key.
    """
    quote = " ".join((claim.quote or "").split()).casefold()
    if quote:
        return quote
    return " ".join(f"{claim.title} {claim.rationale}".split()).casefold()


def extract_claims(doc: Document) -> list[CandidateClaim]:
    """Extract candidate claims from the whole Document.

    A provider failure raises, as it did before; a malformed claim is skipped
    without sinking the rest of the batch.
    """
    chunks = chunk_text(doc.text)
    if len(chunks) > MAX_CHUNKS:
        print(f"  only the first {MAX_CHUNKS} of {len(chunks)} chunks are read")

    claims: list[CandidateClaim] = []
    seen: set[str] = set()
    last = min(len(chunks), MAX_CHUNKS) - 1
    for chunk in chunks[:MAX_CHUNKS]:
        # The opening chunk carries the product/context; the closing one often
        # carries the conclusion or a later owner report. A middle chunk is
        # read only when the deterministic gate says it is worth paying for.
        if chunk.index not in (0, last) and not chunk_has_signal(chunk.text):
            continue
        raw_claims = extract_grounded(chunk.text)
        for c in raw_claims:
            try:
                claim = CandidateClaim(**c)
            except Exception as exc:
                # one malformed/partial claim shouldn't sink the rest
                print(f"  skipped malformed claim: {exc}")
                continue
            key = _claim_key(claim)
            if key in seen:
                continue
            seen.add(key)
            claims.append(claim)
    return claims
