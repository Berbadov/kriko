"""Extraction layer — turns raw source text into structured CandidateClaims.

Uses langextract (packs.cars.pipeline.langextract_client) for grounded, few-shot
extraction over Mistral's ministral-8b-latest: each claim's quote is aligned
to an exact character span in the source text rather than trusted as a
self-reported string, closing a hallucination gap the old raw-JSON approach
left entirely to gate_support's separate LLM call. Accuracy of the *claim
itself* (is this really a known issue, does it belong to this variant) is
still the gate's job, not this layer's — grounding only verifies the quote is
real, not that the claim is true or correctly attributed.

This module runs OFFLINE only — never on the /analyze request path.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from packs.cars.pipeline.util.domains import normalize_domain
from packs.cars.pipeline.langextract_client import extract_grounded
from packs.cars.pipeline.sources.base import Document


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


def extract_claims(doc: Document) -> list[CandidateClaim]:
    """Extract candidate claims from a Document. Returns [] on any error."""
    raw_claims = extract_grounded(doc.text[:6000])

    claims: list[CandidateClaim] = []
    for c in raw_claims:
        try:
            claims.append(CandidateClaim(**c))
        except Exception as exc:
            # one malformed/partial claim shouldn't sink the rest
            print(f"  skipped malformed claim: {exc}")
    return claims
