from enum import Enum
from pydantic import BaseModel


class CoverageState(str, Enum):
    RISKS_FOUND = "risks_found"
    MATCHED_NO_DATA = "matched_no_data"
    NOT_MATCHED = "not_matched"
    UNAVAILABLE = "unavailable"


class SourceRef(BaseModel):
    url: str
    site_or_channel: str | None = None
    quote: str
    timestamp_s: int | None = None


class RiskItem(BaseModel):
    title: str
    severity: str                   # "high" | "medium" | "low"
    domain: str                     # "engine" | "transmission" | "electrical" | ...
    rationale: str
    inspection_advice: str
    sources: list[SourceRef] = []
    source_count: int
    confidence: float | None = None  # HUMAN DECISION #3: shown to buyers or not?
    strength: str = "reported"       # "confirmed" (verified) | "reported" (review/held).
    #   Tells the card whether to assert the issue or label it an unverified report.


class AnalyzeRequest(BaseModel):
    listing_url: str | None = None
    ad_metadata: dict = {}
    debug: bool = False             # ignored on serve path; logged only


class AnalyzeResponse(BaseModel):
    coverage_state: CoverageState
    summary: str                    # NEVER asserts reliability
    risks: list[RiskItem] = []
    disclaimer: str                 # always present
    matched_variant_ids: list[str] = []
    # HUMAN DECISION #1: The current UI (hover_lite.js) only reads `risks` and
    # `summary`. coverage_state, disclaimer, matched_variant_ids are returned
    # here for future UI use, but MATCHED_NO_DATA and UNAVAILABLE currently
    # render identically to a 0-risk RISKS_FOUND unless summary text differs.
    # The UI must be updated to visually distinguish these states.
