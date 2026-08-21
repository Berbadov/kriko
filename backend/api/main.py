"""FastAPI application — serving plane only.

No LLM, no web requests, no vector search on this path.
Every request is a plain DB lookup: match variant → read claims → return.
"""

import time
import uuid
import logging
from dataclasses import asdict
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.api.schemas import (
    AnalyzeRequest, AnalyzeResponse, BuildStamp, CoverageState, RiskItem,
    SourceRef, SubsystemGroup,
)
from backend import config
from backend.config import ALLOWED_ORIGINS, STANDARD_DISCLAIMER
from backend.core.context import ListingContext
from backend.core.matcher import MatchResult, match_variant
from backend.core.recover import recover_listing_fields
from backend.core.resolver import ClaimResult, resolve_claims
from backend.db.models import AnalysisLog, Claim, ClaimSource, Variant
from backend.db.session import db_reachable, get_db
from backend.observability import log_analysis_jsonl, read_recent

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
    # commit/build_time: deploy-staleness stamp (B15) — an operator can diff the
    # served commit against HEAD instead of discovering a stale image from
    # pre-fix behaviour in production.
    return {
        "status": "ok",
        "db": "reachable" if db_reachable() else "unreachable",
        "commit": config.GIT_COMMIT,
        "build_time": config.GIT_BUILD_TIME,
    }


# ── Analyze ──────────────────────────────────────────────────────────────────

# Appended to the summary when the ad's stated transmission contradicts the
# cataloged gearbox of the matched variant (MatchResult.tx_mismatch). Additive
# only — the extension reads `summary`, so the caveat is buyer-visible without
# any new response field.
TX_MISMATCH_CAVEAT = (
    "Heads up: this listing's stated transmission does not match the gearbox "
    "cataloged for the matched variant, so gearbox-specific risks are not covered "
    "here — confirm the transmission with the seller."
)

# The per-listing "few" ceiling: a buyer sees at most this many risks. Tunable.
MAX_RISKS_PER_LISTING = 8

# ── Serving payload v2: relevance score + why_shown ──────────────────────────
#
# relevance_score = severity weight × mileage-gate match × detection factor.
# It is the primary rank key: what an expert inspection catches anyway
# (visual detection) and what only *might* apply (mileage gate unverifiable)
# sink below claims that demonstrably apply to this specific car — without
# ever being dropped (fail-open).

_SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}
# A mileage gate the listing can't confirm (mileage unknown) still serves the
# claim (fail-open) but ranks it below claims whose applicability is confirmed.
_MILEAGE_UNKNOWN_FACTOR = 0.7

# why_shown fragment for a suppressed visual-detection claim. Mirrors
# resolver.VISUAL_DETECTION_FACTOR — the factor lives in the resolver (where
# suppression is decided), the buyer-facing wording lives here.
_VISUAL_WHY = "standard inspection usually catches this — low priority"

# Phase 1 (source quality): the claim's best source tier multiplies relevance.
# Authoritative recall data outranks a specialist writeup, which outranks an
# SEO blog. NULL trust (no sources — maintenance claims) is neutral (1.0),
# never a penalty: the maintenance trust model is the service interval, not
# the source list.
_TRUST_WHY = {
    "authoritative": "confirmed by official recall/TSB data",
    "manufacturer": "confirmed by manufacturer data",
    "specialist": "corroborated by a specialist source",
}

# Registry subsystem top-level group (the part before "/") → Turkish label for
# the subsystems[] group header. Closed vocabulary — mirrors the groups defined
# in knowledge/catalog/components.yaml, not per-model data.
_SUBSYSTEM_TR = {
    "engine": "Motor",
    "transmission": "Şanzıman",
    "emissions": "Egzoz & Emisyon",
    "electrical": "Elektrik",
    "body": "Gövde",
    "brakes": "Frenler",
    "suspension": "Süspansiyon",
    "steering": "Direksiyon",
    "cooling": "Soğutma",
    "fuel": "Yakıt Sistemi",
    "exhaust": "Egzoz",
    "interior": "İç Mekan",
}
_OTHER_SUBSYSTEM_TR = "Diğer"

# Strengths that are evidence-backed and must never be dropped by the cap — only
# the unverified "reported" tail is trimmed.
_PROTECTED_STRENGTHS = frozenset({"confirmed", "due", "due_stated"})


def _cap_risks(risks: list[RiskItem], n: int) -> list[RiskItem]:
    """Cap a ranked risk list to `n`, never dropping evidence-backed items.

    Keeps every protected (confirmed/due/due_stated) risk, then fills the
    remaining slots with the top-ranked reported items. Input is assumed already
    ranked best-first; output preserves that order. If protected items alone
    exceed `n`, they are all kept (never hide a confirmed/due risk to meet a cap).
    """
    protected = [r for r in risks if r.strength in _PROTECTED_STRENGTHS]
    slots_for_reported = max(0, n - len(protected))
    kept: list[RiskItem] = []
    reported_kept = 0
    for r in risks:
        if r.strength in _PROTECTED_STRENGTHS:
            kept.append(r)
        elif reported_kept < slots_for_reported:
            kept.append(r)
            reported_kept += 1
    return kept


def _build_stamp() -> BuildStamp:
    """The deploy-staleness stamp (B15), attached to every /analyze response:
    the extension footer renders it for the buyer, and the analyses.jsonl record
    keeps it so replay debugging knows which build produced a logged response.
    """
    return BuildStamp(commit=config.GIT_COMMIT, build_time=config.GIT_BUILD_TIME)


def run_analysis(
    meta: dict, db: Session,
) -> tuple[ListingContext, MatchResult, list[ClaimResult], AnalyzeResponse]:
    """The actual serve path: ad_metadata -> (context, match, served claims, response).

    Pulled out of the /analyze route so backend/tools/replay.py can re-run a
    logged request through the *real* pipeline rather than a hand-copied
    reimplementation that could silently drift from it.
    """
    # The extension's DOM scrape is one fragile source for every required field
    # (Sahibinden redesigns the info-list markup, and the whole payload goes
    # empty). Fill what it missed from the listing's URL slug and title before
    # matching — never overwriting what it did read. See backend/core/recover.py.
    meta = recover_listing_fields(meta)

    ctx = ListingContext(
        mileage_km   = meta.get("mileage_km"),
        age_years    = (date.today().year - meta["year"]) if meta.get("year") else None,
        model_year   = meta.get("year"),
        annual_km    = meta.get("annual_km"),
        fuel_type    = meta.get("fuel_type"),
        transmission = meta.get("transmission"),
        description  = (meta.get("description") or "").lower(),
        equipment    = meta.get("equipment") or None,
    )

    match  = match_variant(meta, db)
    served = resolve_claims(match, db, ctx)

    state = _coverage_state(match, served)
    # v2 why_shown: the config-match reason is listing-level (same string on
    # every card); per-claim reasons are computed in _claim_to_risk.
    variant_rows = (
        db.query(Variant).filter(Variant.id.in_(match.variant_ids)).all()
        if match.variant_ids else []
    )
    config_why = (
        "Config match: " + ", ".join(_variant_label(v) for v in variant_rows)
        if variant_rows else None
    )
    risks = [_claim_to_risk(cr, db, ctx, config_why) for cr in served]
    # Priority key (serving payload v2): relevance_score first — severity
    # weight × mileage-gate match × detection factor — so risks that
    # demonstrably apply to THIS car outrank inspection-catchable or
    # only-maybe-applicable ones. The old key (strength → consequence →
    # severity) stays as the tiebreak for equal scores.
    _SEV_RANK = {"high": 0, "medium": 1, "low": 2}
    _CONSEQ_RANK = {"high": 0, "medium": 1, "low": 2}
    _STRENGTH_RANK = {"confirmed": 0, "due": 1, "due_stated": 2, "reported": 3}
    risks.sort(key=lambda r: (
        -(r.relevance_score or 0.0),
        _STRENGTH_RANK.get(r.strength, 4),
        _CONSEQ_RANK.get(r.consequence, 1),
        _SEV_RANK.get(r.severity, 3),
    ))
    risks = _cap_risks(risks, MAX_RISKS_PER_LISTING)
    subsystems = _group_subsystems(risks)

    summary = _build_summary(state, match, risks)
    if match.tx_mismatch:
        summary = f"{summary} {TX_MISMATCH_CAVEAT}"

    resp = AnalyzeResponse(
        coverage_state=state,
        summary=summary,
        risks=risks,
        subsystems=subsystems,
        disclaimer=STANDARD_DISCLAIMER,
        matched_variant_ids=match.variant_ids,
        build=_build_stamp(),
    )
    return ctx, match, served, resp


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    started = time.monotonic()
    meta    = dict(payload.ad_metadata or {})
    # The URL is a recovery source (its slug names the make/model), so make sure
    # it is present even if the scrape produced no `url` field of its own.
    if not meta.get("url") and payload.listing_url:
        meta["url"] = payload.listing_url

    try:
        ctx, match, served, resp = run_analysis(meta, db)
    except Exception as exc:
        log.exception("analyze error for meta=%r", _safe_meta(meta))
        # HUMAN DECISION: return 200+UNAVAILABLE vs raise 5xx.
        # 5xx causes background.js to show "Analysis failed" (honest).
        # 200+UNAVAILABLE with risks=[] looks identical to 0 risks in current UI.
        # We return 200+UNAVAILABLE and rely on summary text to signal it.
        resp = _unavailable_response()
        _log_analysis_jsonl(payload, None, None, resp, started, error=str(exc))
        return resp

    _log_analysis(db, meta, match, served, resp, started)
    _log_analysis_jsonl(payload, ctx, match, resp, started)
    return resp


# ── Debug read path (docs/design_flaws.md "Observability gap") ─────────────

@app.get("/debug/analyses")
def debug_analyses(limit: int = 20, model: str | None = None):
    """Recent full /analyze payloads, off by default — see ENABLE_DEBUG_ENDPOINT.

    Primary read path is the CLI (`python -m backend.tools.analyses`), which reads
    the same JSONL file with no auth story needed. This endpoint exists for when
    only HTTP access (not shell access) to the deploy host is available, and must
    be explicitly turned on to use it.
    """
    if not config.ENABLE_DEBUG_ENDPOINT:
        raise HTTPException(status_code=404)
    return {"analyses": read_recent(limit=limit, model=model)}


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
        # The error path is where the stamp matters most — a buyer seeing
        # "unavailable" on a stale deploy is exactly the B15 incident shape.
        build=_build_stamp(),
    )


def _claim_to_risk(
    cr: ClaimResult, db: Session,
    ctx: ListingContext | None = None,
    config_why: str | None = None,
) -> RiskItem:
    claim = cr.claim
    sources_rows = (
        db.query(ClaimSource)
        .filter(ClaimSource.claim_id == claim.id)
        .all()
    )

    # ── v2 relevance score + why_shown ───────────────────────────────────
    mileage_factor, mileage_why = _mileage_gate(claim, ctx)
    severity_w = _SEVERITY_WEIGHT.get((claim.severity or "").lower(), 0.6)
    trust = claim.source_trust if claim.source_trust is not None else 1.0
    relevance = round(severity_w * mileage_factor * cr.detection_factor * trust, 4)

    why_shown: list[str] = []
    if config_why:
        why_shown.append(config_why)
    if mileage_why:
        why_shown.append(mileage_why)
    if cr.detection_factor < 1.0:
        why_shown.append(_VISUAL_WHY)
    trust_why = _TRUST_WHY.get(claim.source_tier or "")
    if trust_why:
        why_shown.append(trust_why)

    return RiskItem(
        title=claim.title,
        severity=claim.severity,
        consequence=claim.consequence or "medium",
        domain=claim.domain,
        rationale=claim.rationale,
        inspection_advice=claim.inspection_advice,
        confidence=claim.confidence,
        strength=cr.strength,
        claim_key=claim.claim_key,
        component_id=claim.component_id,
        subsystem=claim.subsystem,
        source_tier=claim.source_tier,
        relevance_score=relevance,
        why_shown=why_shown,
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


def _fmt_km(n: int) -> str:
    """Turkish-style thousand separator: 187000 → '187.000' (matches the
    Sahibinden listing format buyers see)."""
    return f"{n:,}".replace(",", ".")


def _variant_label(v: Variant) -> str:
    """Human-readable label for a matched variant — the 'config match' reason
    in why_shown. Built from the catalog row (no display name column exists),
    with the stable variant id appended so the label stays unambiguous for
    ambiguous multi-variant matches."""
    parts = [v.make.title(), v.model.title()]
    if v.generation:
        parts.append(str(v.generation))
    if v.power_min_hp:
        if v.power_max_hp and v.power_max_hp != v.power_min_hp:
            parts.append(f"{v.power_min_hp}-{v.power_max_hp} hp")
        else:
            parts.append(f"{v.power_min_hp} hp")
    return f"{' '.join(p for p in parts if p)} ({v.id})"


def _mileage_gate(claim: Claim, ctx: ListingContext | None) -> tuple[float, str | None]:
    """(factor, why_shown) for the claim's applies_when mileage gates.

    Gate satisfied by the listing's mileage → 1.0 plus a human-readable
    threshold string ("187.000 km > 120.000 km threshold"). Gate present but
    mileage unknown → _MILEAGE_UNKNOWN_FACTOR and the fail-open wording — the
    claim still serves, ranked below confirmed-applicable ones. No mileage
    gate → 1.0, no string (nothing to explain). Age/year-only gates don't
    factor in: the buyer-facing string is about mileage.
    """
    has_min = claim.min_mileage_km is not None
    has_max = claim.max_mileage_km is not None
    if not (has_min or has_max):
        return 1.0, None
    m = ctx.mileage_km if ctx is not None else None
    if m is None:
        return _MILEAGE_UNKNOWN_FACTOR, "mileage unknown — shown by default"
    if has_min and m >= claim.min_mileage_km:
        op = "≥" if m == claim.min_mileage_km else ">"
        return 1.0, f"{_fmt_km(m)} km {op} {_fmt_km(claim.min_mileage_km)} km threshold"
    if has_max and m <= claim.max_mileage_km:
        op = "≤" if m == claim.max_mileage_km else "<"
        return 1.0, f"{_fmt_km(m)} km {op} {_fmt_km(claim.max_mileage_km)} km ceiling"
    return 1.0, None


def _group_subsystems(risks: list[RiskItem]) -> list[SubsystemGroup]:
    """Group ranked risks by registry subsystem for the v2 payload.

    Claims without a subsystem (no component_id — YAMLs not yet migrated)
    land in the "other" bucket. Input order is the ranked order, so groups
    appear best-risk-first and each group's cards keep the global ranking.
    """
    groups: dict[str, list[RiskItem]] = {}
    for r in risks:
        groups.setdefault(r.subsystem or "other", []).append(r)
    out: list[SubsystemGroup] = []
    for name, items in groups.items():
        if name == "other":
            display_tr = _OTHER_SUBSYSTEM_TR
        else:
            top = name.split("/", 1)[0]
            display_tr = _SUBSYSTEM_TR.get(top, top)
        out.append(SubsystemGroup(name=name, display_tr=display_tr, risks=items))
    return out


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


def _log_analysis_jsonl(
    payload: AnalyzeRequest,
    ctx: ListingContext | None,
    match: MatchResult | None,
    resp: AnalyzeResponse,
    started: float,
    error: str | None = None,
) -> None:
    """Full-payload log — request + gating context + full response, one line per
    analysis. Answers "what did the buyer see and why" after the fact, and is the
    input backend/tools/replay.py needs to re-run a logged request through a fix.

    Entire body is best-effort, same as _log_analysis: logging must never break
    the serve path, including record construction, not just the file write.
    """
    try:
        record = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "listing_url": payload.listing_url,
            "ad_metadata": payload.ad_metadata,
            "debug": payload.debug,
            "context": asdict(ctx) if ctx is not None else None,
            "match": (
                {"variant_ids": match.variant_ids, "method": match.method, "notes": match.notes}
                if match is not None else None
            ),
            "response": resp.model_dump(mode="json"),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if error is not None:
            record["error"] = error
        log_analysis_jsonl(record)
    except Exception:
        log.warning("Failed to build analyses.jsonl record", exc_info=True)
