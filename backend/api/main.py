"""FastAPI application — serving plane only.

No LLM, no web requests, no vector search on this path.
Every request is a plain DB lookup: match variant → read claims → return.
"""

import time
import uuid
import logging
from datetime import date

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.api.schemas import (
    AnalyzeRequest, AnalyzeResponse, CoverageState, RiskItem, SourceRef,
)
from backend.config import ALLOWED_ORIGINS, STANDARD_DISCLAIMER
from backend.core.context import ListingContext
from backend.core.matcher import MatchResult, match_variant
from backend.core.resolver import ClaimResult, resolve_claims
from backend.db.models import AnalysisLog, ClaimSource
from backend.db.session import db_reachable, get_db

log = logging.getLogger(__name__)

app = FastAPI(title="Kriko API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "db": "reachable" if db_reachable() else "unreachable"}


# ── Analyze ──────────────────────────────────────────────────────────────────

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    started = time.monotonic()
    meta    = payload.ad_metadata or {}

    ctx = ListingContext(
        mileage_km   = meta.get("mileage_km"),
        age_years    = (date.today().year - meta["year"]) if meta.get("year") else None,
        annual_km    = meta.get("annual_km"),
        fuel_type    = meta.get("fuel_type"),
        transmission = meta.get("transmission"),
        description  = (meta.get("description") or "").lower(),
    )

    try:
        match  = match_variant(meta, db)
        served = resolve_claims(match, db, ctx)
    except Exception:
        log.exception("analyze error for meta=%r", _safe_meta(meta))
        # HUMAN DECISION: return 200+UNAVAILABLE vs raise 5xx.
        # 5xx causes background.js to show "Analysis failed" (honest).
        # 200+UNAVAILABLE with risks=[] looks identical to 0 risks in current UI.
        # We return 200+UNAVAILABLE and rely on summary text to signal it.
        return _unavailable_response()

    state = _coverage_state(match, served)
    risks = [_claim_to_risk(cr, db) for cr in served]
    _SEV_RANK = {"high": 0, "medium": 1, "low": 2}
    _STRENGTH_RANK = {"confirmed": 0, "due": 1, "due_stated": 2, "reported": 3}
    risks.sort(key=lambda r: (_STRENGTH_RANK.get(r.strength, 4), _SEV_RANK.get(r.severity, 3)))

    resp = AnalyzeResponse(
        coverage_state=state,
        summary=_build_summary(state, match, risks),
        risks=risks,
        disclaimer=STANDARD_DISCLAIMER,
        matched_variant_ids=match.variant_ids,
    )

    _log_analysis(db, meta, match, served, resp, started)
    return resp


# ── Helpers ──────────────────────────────────────────────────────────────────

def _coverage_state(match: MatchResult, served: list) -> CoverageState:
    if served:
        return CoverageState.RISKS_FOUND
    if match.variant_ids:
        return CoverageState.MATCHED_NO_DATA
    return CoverageState.NOT_MATCHED


def _build_summary(state: CoverageState, match: MatchResult, risks: list[RiskItem]) -> str:
    if state == CoverageState.RISKS_FOUND:
        confirmed = [r for r in risks if r.strength == "confirmed"]
        due       = [r for r in risks if r.strength in ("due", "due_stated")]
        reported  = [r for r in risks if r.strength == "reported"]
        variant_label = ", ".join(match.variant_ids)

        # Only `confirmed` (corroborated) claims may be called "known issues".
        # `reported` claims are unverified community reports — phrased as such so
        # the summary never asserts reliability about a single-source rumour.
        parts = []
        if confirmed:
            parts.append(
                f"{len(confirmed)} confirmed issue{'s' if len(confirmed) != 1 else ''}"
            )
        if due:
            parts.append(
                f"{len(due)} maintenance item{'s' if len(due) != 1 else ''} due"
            )
        if reported:
            parts.append(
                f"{len(reported)} unverified report{'s' if len(reported) != 1 else ''}"
            )
        lead = " and ".join(parts)
        return (
            f"{lead} for this variant ({variant_label}). "
            "Confirmed issues are corroborated reliability patterns; unverified "
            "reports are single low-trust mentions shown for awareness only. "
            "Either way, get a pre-purchase inspection."
        )
    if state == CoverageState.MATCHED_NO_DATA:
        return (
            f"Variant identified ({', '.join(match.variant_ids)}) but no verified issues "
            "in our database yet. This does NOT mean the car is problem-free — "
            "always get an independent pre-purchase inspection."
        )
    if state == CoverageState.NOT_MATCHED:
        return (
            "Could not identify the exact variant from this listing's data. "
            f"Reason: {match.notes} "
            "No data can be shown — get an independent pre-purchase inspection."
        )
    # UNAVAILABLE
    return (
        "Kriko could not check this car (service temporarily unavailable). "
        "This is NOT a clean result — please try again or get an inspection."
    )


def _unavailable_response() -> AnalyzeResponse:
    return AnalyzeResponse(
        coverage_state=CoverageState.UNAVAILABLE,
        summary=(
            "Kriko could not check this car (service temporarily unavailable). "
            "This is NOT a clean result — please try again or get an inspection."
        ),
        risks=[],
        disclaimer=STANDARD_DISCLAIMER,
        matched_variant_ids=[],
    )


def _claim_to_risk(cr: ClaimResult, db: Session) -> RiskItem:
    claim = cr.claim
    sources_rows = (
        db.query(ClaimSource)
        .filter(ClaimSource.claim_id == claim.id)
        .all()
    )
    return RiskItem(
        title=claim.title,
        severity=claim.severity,
        domain=claim.domain,
        rationale=claim.rationale,
        inspection_advice=claim.inspection_advice,
        confidence=claim.confidence,
        strength=cr.strength,
        sources=[
            SourceRef(
                url=s.source_url,
                site_or_channel=s.site_or_channel,
                quote=s.quote,
                timestamp_s=s.timestamp_s,
            )
            for s in sources_rows
        ],
        source_count=len(sources_rows),
    )


def _log_analysis(
    db: Session, meta: dict, match: MatchResult,
    served: list, resp: AnalyzeResponse, started: float,
) -> None:
    try:
        duration_ms = int((time.monotonic() - started) * 1000)
        row = AnalysisLog(
            id=str(uuid.uuid4()),
            listing_url=meta.get("url"),
            make=meta.get("make"),
            model=meta.get("model"),
            year=meta.get("year"),
            fuel_type=meta.get("fuel_type"),
            engine_cc=meta.get("engine_volume_cc"),
            power_hp=meta.get("power_hp"),
            transmission=meta.get("transmission"),
            candidate_variant_ids=match.variant_ids,
            matched_variant_ids=resp.matched_variant_ids,
            coverage_state=resp.coverage_state.value,
            match_method=match.method,
            match_notes=match.notes,
            claim_ids_returned=[cr.claim.id for cr in served],
            claims_returned=len(served),
            duration_ms=duration_ms,
        )
        db.add(row)
        db.commit()
    except Exception:
        log.warning("Failed to write analysis_log", exc_info=True)


def _safe_meta(meta: dict) -> dict:
    """Minimal fields safe to log without PII."""
    return {k: meta.get(k) for k in ("make", "model", "year", "fuel_type")}
