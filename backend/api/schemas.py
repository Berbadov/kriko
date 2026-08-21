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
    consequence: str = "medium"     # deterministic failure-system tier; primary rank key after strength
    domain: str                     # "engine" | "transmission" | "electrical" | ...
    rationale: str
    inspection_advice: str
    sources: list[SourceRef] = []
    source_count: int
    confidence: float | None = None  # HUMAN DECISION #3: shown to buyers or not?
    strength: str = "reported"       # "confirmed" (verified) | "reported" (review/held).
    #   Tells the card whether to assert the issue or label it an unverified report.
    # ── serving payload v2 (Phase 3) ────────────────────────────────────────
    claim_key: str | None = None     # stable claim identity (survives version bumps) — gold-set key
    component_id: str | None = None  # registry component id, when the claim has one
    subsystem: str | None = None     # registry subsystem (e.g. "engine/timing") — grouping key
    source_tier: str | None = None   # best source tier (authoritative|specialist|forum_ugc|seo_blog|manufacturer)
    relevance_score: float | None = None
    #   severity weight × mileage-gate match × detection factor. Primary rank key.
    why_shown: list[str] = []        # human-readable reasons this card is in the payload:
    #   config match, mileage gate (satisfied/unknown), detection suppression.


class SubsystemGroup(BaseModel):
    """Risks grouped by registry subsystem (serving payload v2) — the v2 UI
    renders these as sections; the flat `risks` array stays for the current
    extension (backward compat)."""
    name: str                        # registry subsystem, e.g. "engine/timing"; "other" when unknown
    display_tr: str | None = None    # Turkish group label for the panel header
    risks: list[RiskItem] = []


class BuildStamp(BaseModel):
    """Deploy-staleness stamp (backlog B15) — which commit the serving artifact
    was built from, and when. "unknown" when the deploy was never stamped."""
    commit: str = "unknown"
    build_time: str = "unknown"


class AnalyzeRequest(BaseModel):
    listing_url: str | None = None
    ad_metadata: dict = {}
    debug: bool = False             # ignored on serve path; logged only


class AnalyzeResponse(BaseModel):
    coverage_state: CoverageState
    summary: str                    # NEVER asserts reliability
    risks: list[RiskItem] = []      # flat ranked list — current extension reads this
    subsystems: list[SubsystemGroup] = []  # same risks grouped by registry subsystem (v2 UI)
    disclaimer: str                 # always present
    matched_variant_ids: list[str] = []
    build: BuildStamp = BuildStamp()  # serving build — extension footer + replay log
    # HUMAN DECISION #1: The current UI (hover_lite.js) only reads `risks` and
    # `summary`. coverage_state, disclaimer, matched_variant_ids are returned
    # here for future UI use, but MATCHED_NO_DATA and UNAVAILABLE currently
    # render identically to a 0-risk RISKS_FOUND unless summary text differs.
    # The UI must be updated to visually distinguish these states.
