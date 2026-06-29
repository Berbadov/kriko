"""Resolve a MatchResult to servable claims.

Servable = `verified` (corroborated → shown as "confirmed") plus `review`/`held`
(thinly-corroborated community reports → shown to buyers as clearly-labelled
"reported", never asserted as fact). The strength distinction is preserved all
the way to the card; this module only decides *whether* a claim is shown.
`draft` and anything sourceless is never served.

Ambiguous match → intersection: only claims servable for ALL surviving
candidates are returned. Unique-to-one claims are withheld — safe regardless
of which variant the car actually is.

Maintenance claims (kind="maintenance") are exempt from the has_source
requirement — their grounding is the manufacturer service interval, not a
ClaimSource row. They are gated instead by interval logic in
_resolve_maintenance_strength.
"""

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.context import ListingContext
from backend.core.matcher import MatchResult
from backend.db.models import Claim, ClaimSource, ClaimVariant

# Statuses a buyer may see. `verified` → "confirmed"; review/held → "reported".
# `draft` is never servable. The card labels strength so the two never blur.
SERVABLE_STATUSES = ("verified", "review", "held")


@dataclass
class ClaimResult:
    """A claim resolved for a specific listing, with its runtime strength."""
    claim: Claim
    strength: str  # "confirmed" | "reported" | "due" | "due_stated"


def resolve_claims(
    match: MatchResult,
    db: Session,
    ctx: ListingContext | None = None,
) -> list[ClaimResult]:
    if not match.variant_ids:
        return []
    if len(match.variant_ids) == 1:
        return _apply_context(_servable_claims_for(match.variant_ids[0], db), ctx)

    # Ambiguous: union across all candidates — a buyer needs to know the risks
    # of any variant the car could be. Intersection silently drops variant-specific
    # claims (e.g. EDC transmission warnings) when transmission isn't in the listing.
    all_claims: dict[int, Claim] = {}
    for v in match.variant_ids:
        for c in _servable_claims_for(v, db):
            all_claims[c.id] = c
    if not all_claims:
        return []
    return _apply_context(list(all_claims.values()), ctx)


def _apply_context(claims: list[Claim], ctx: ListingContext | None) -> list[ClaimResult]:
    """Apply mileage/age gating and maintenance interval logic, return ClaimResults."""
    results = []
    for claim in claims:
        if claim.kind == "maintenance":
            strength = _resolve_maintenance_strength(claim, ctx)
            if strength is None:
                continue  # not due → hide
            results.append(ClaimResult(claim=claim, strength=strength))
        else:
            if not _passes_applies_when(claim, ctx):
                continue
            strength = "confirmed" if claim.status == "verified" else "reported"
            results.append(ClaimResult(claim=claim, strength=strength))
    return results


def _passes_applies_when(claim: Claim, ctx: ListingContext | None) -> bool:
    """Return True if the claim's applies_when conditions are met. Fail-open on missing data."""
    if ctx is None:
        return True
    # When ctx has the data and the claim has a gate, apply it.
    # When ctx.mileage_km/age_years is None but the claim has a gate → skip that
    # dimension (fail-open) — never hide a risk because data is missing.
    if claim.min_mileage_km is not None and ctx.mileage_km is not None:
        if ctx.mileage_km < claim.min_mileage_km:
            return False
    if claim.max_mileage_km is not None and ctx.mileage_km is not None:
        if ctx.mileage_km > claim.max_mileage_km:
            return False
    if claim.min_age_years is not None and ctx.age_years is not None:
        if ctx.age_years < claim.min_age_years:
            return False
    return True


def _resolve_maintenance_strength(
    claim: Claim,
    ctx: ListingContext | None,
) -> str | None:
    """Determine if a maintenance claim is due and return its strength, or None to hide.

    Returns:
        "due"        — interval reached, ad gives no evidence of recent service
        "due_stated" — interval reached, ad text mentions relevant service keywords
        None         — interval not reached, hide the claim
    """
    m = claim.maintenance_data or {}
    interval_km = m.get("interval_km")
    interval_years = m.get("interval_years")
    keywords: list[str] = m.get("evidence_keywords", [])

    due = False
    data_used = False
    if ctx is not None:
        if ctx.mileage_km is not None and interval_km is not None:
            data_used = True
            if ctx.mileage_km >= interval_km:
                due = True
        if ctx.age_years is not None and interval_years is not None:
            data_used = True
            if ctx.age_years >= interval_years:
                due = True

    if not data_used:
        due = True  # fail-open: no mileage/age available → show

    if not due:
        return None  # not due → hide

    description = ctx.description if ctx else ""
    has_evidence = any(kw.lower() in description for kw in keywords)
    return "due_stated" if has_evidence else "due"


def _claims_share_domain(a: Claim, b: Claim) -> bool:
    return bool(a.domain and b.domain and a.domain == b.domain)


def annotate_coherence(results: list[ClaimResult]) -> list[ClaimResult]:
    """Ensure coherence within each domain's maintenance claims.

    When two maintenance claims from the same domain produce contradictory strength
    signals (one 'due', one 'due_stated'), keep both — the buyer should see both
    the 'needs doing' signal and the 'seller claims done' caveat. This function
    is a no-op in the current serving logic but is the extension point for
    per-part coherence as the part catalog grows.
    """
    # Group by domain → if any 'due_stated' exists alongside 'due', no suppression.
    # Current behaviour already satisfies this (both are returned). This function
    # documents the invariant explicitly.
    return results


def _servable_claims_for(variant_id: str, db: Session) -> list[Claim]:
    """Fetch claims, re-checking invariants at query time.

    Invariant: status ∈ SERVABLE_STATUSES AND is_current AND (≥1 source OR
    kind="maintenance") AND variant link. Re-checked here, not trusted from
    the YAML/sync path. The has_source requirement drops the ungrounded score=0
    noise (those claims are persisted with zero sources), so only grounded
    reports reach a buyer. Maintenance claims are exempted — their grounding is
    the manufacturer service interval.
    """
    has_source = (
        db.query(ClaimSource)
        .filter(ClaimSource.claim_id == Claim.id)
        .exists()
    )
    return (
        db.query(Claim)
        .join(ClaimVariant, Claim.id == ClaimVariant.claim_id)
        .filter(
            ClaimVariant.variant_id == variant_id,
            Claim.status.in_(SERVABLE_STATUSES),
            Claim.is_current == True,
            or_(
                Claim.kind == "maintenance",
                has_source,
            ),
        )
        .all()
    )
