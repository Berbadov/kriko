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

High-severity human-review gate (docs/design_flaws.md Flaw 4): `severity ==
"high"` already forces `promote.py` to mark a claim `review`/`held` pending a
human sign-off that, in practice, never happens — nearly everything in the
catalog sits at `promoted_by: pending_human`. Serving those anyway made the
effective quality bar "survived a ministral-8b gate", for exactly the claims
most likely to weigh on a buyer's decision. A high-severity claim is now
withheld until a human actually promotes it to `verified`; medium/low
review/held claims still serve as "reported" — same as before.
"""

from dataclasses import dataclass
import logging
import re

from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import Session

from backend.core.context import ListingContext
from backend.core.equipment import listing_has_equipment
from backend.core.matcher import MatchResult
from backend.core.normalize import normalize_transmission
from backend.core.title_sim import title_similar
from backend.core.transmission_signal import (
    claim_signals_automatic_only, claim_signals_manual_only,
)
from backend.db.models import Claim, ClaimSource, ClaimVariant

log = logging.getLogger(__name__)

# Statuses a buyer may see. `verified` → "confirmed"; review/held → "reported".
# `draft` is never servable. The card labels strength so the two never blur.
# See the module docstring: severity=="high" narrows this further at query time.
SERVABLE_STATUSES = ("verified", "review", "held")

# review/held statuses withheld from serving when severity is high — see the
# module docstring's "High-severity human-review gate".
_UNREVIEWED_STATUSES = ("review", "held")


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
        auto_only_ids = _automatic_transmission_claim_ids(match.variant_ids[0], db)
        results = _apply_context(_servable_claims_for(match.variant_ids[0], db), ctx, auto_only_ids)
        return _deduplicate_results(results)

    # Ambiguous: union across all candidates — a buyer needs to know the risks
    # of any variant the car could be. Intersection silently drops variant-specific
    # claims (e.g. EDC transmission warnings) when transmission isn't in the listing.
    all_claims: dict[int, Claim] = {}
    auto_only_ids: set[str] = set()
    for v in match.variant_ids:
        auto_only_ids |= _automatic_transmission_claim_ids(v, db)
        for c in _servable_claims_for(v, db):
            all_claims[c.id] = c
    if not all_claims:
        return []
    results = _apply_context(list(all_claims.values()), ctx, auto_only_ids)
    return _deduplicate_results(results)


def _apply_context(
    claims: list[Claim],
    ctx: ListingContext | None,
    auto_only_claim_ids: set[str] = frozenset(),
) -> list[ClaimResult]:
    """Apply mileage/age gating and maintenance interval logic, return ClaimResults."""
    results = []
    for claim in claims:
        if not _passes_equipment_gate(claim, ctx):
            continue
        if not _passes_transmission_gate(claim, ctx, auto_only_claim_ids):
            continue
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
    # Model-year window: hide a build-year-scoped defect on cars outside its range
    # (e.g. fixed from MY2023). Inclusive bounds; fail-open when the listing year
    # is unknown — never hide a risk on missing data.
    if claim.applies_year_from is not None and ctx.model_year is not None:
        if ctx.model_year < claim.applies_year_from:
            return False
    if claim.applies_year_to is not None and ctx.model_year is not None:
        if ctx.model_year > claim.applies_year_to:
            return False
    return True


def _passes_equipment_gate(claim: Claim, ctx: ListingContext | None) -> bool:
    """Hide claims that require optional equipment (e.g. sunroof) the listing
    confirms the car doesn't have. Unlike mileage/age, this fails CLOSED on a
    confirmed mismatch — a 4WD/sunroof-only claim on a 2WD/no-sunroof car isn't
    a probabilistic risk, it's categorically wrong and undermines trust.

    Still fails open when equipment wasn't scraped at all (ctx.equipment is
    None/empty): we can't distinguish "car doesn't have it" from "extraction
    didn't find the Donanım block", so we never hide on that ambiguity.
    """
    tags = claim.requires_equipment or []
    if not tags:
        return True
    if ctx is None or not ctx.equipment:
        return True
    return all(listing_has_equipment(tag, ctx.equipment) for tag in tags)


# ── Ad-vs-catalog transmission mismatch (matcher.py can't always tell) ───────
#
# matcher.py matches a listing to a Variant purely on cc+hp+fuel+year, then
# narrows by transmission — but _narrow_by_transmission is a *soft* filter:
# if no candidate's cataloged transmission matches what the ad reports, it
# falls back to the unnarrowed set rather than rejecting the match (unlike
# the cc/hp plausibility gate, which does reject via "inconsistent_listing").
# Concretely: the Golf 7 GTI catalog rows (golf7_ea888_220/230) are cataloged
# automatic-only (DQ250/DQ381) even though both also shipped with a 6-speed
# manual — so a real manual GTI ad still "exact"-matches the automatic row,
# and every DQ250 claim linked to it (mechatronic failure, wet-clutch wear,
# ...) would otherwise be served to a buyer whose car has no DSG at all.
#
# Rather than reject the whole match (which would also hide genuinely valid
# engine-only claims like turbo/timing-chain issues), gate out just the
# claims that are transmission-mechanism-specific — same "fails closed only
# on a confirmed mismatch" shape as _passes_equipment_gate above.
#
# Two independent signals decide "transmission-mechanism-specific", since
# neither alone covers the live claim set:
#   1. Provenance: the claim reached this variant via a dedicated automatic
#      gearbox part (DQ200/DQ250/DQ381/EDC/...; see sync.py's
#      `grounding_note`) — true regardless of wording, since every claim in
#      e.g. dq250.yaml is inherently DSG-specific even when a given title
#      ("Clutch Pack Wear in High-Torque Applications") doesn't say "DSG".
#   2. Text: a claim filed under a *different* part (e.g. an electrical-file
#      claim about "DSG-related electrical gremlins") still names the
#      mechanism in its own title/rationale — reuses the same vocabulary as
#      sync.py's catalog-side _transmission_compatible.
_GROUNDING_PART_RE = re.compile(r"^Part fitment: (?P<part_id>\S+) \((?P<part_type>\w+)\)$")


def _automatic_transmission_claim_ids(variant_id: str, db: Session) -> set[str]:
    """Claim IDs whose *only* route to this variant is a dedicated automatic
    gearbox part (part_type=="transmission", part_id != "manual") — see the
    module note above `_GROUNDING_PART_RE`.
    """
    rows = (
        db.query(ClaimVariant.claim_id, ClaimVariant.grounding_note)
        .filter(ClaimVariant.variant_id == variant_id)
        .all()
    )
    ids = set()
    for claim_id, note in rows:
        m = _GROUNDING_PART_RE.match(note or "")
        if m and m.group("part_type") == "transmission" and m.group("part_id") != "manual":
            ids.add(claim_id)
    return ids


def _passes_transmission_gate(
    claim: Claim, ctx: ListingContext | None, auto_only_claim_ids: set[str],
) -> bool:
    """Hide claims that require a transmission mechanism the ad's own stated
    transmission rules out. Fails open when the ad doesn't state a
    (normalizable) transmission at all — see module note above.
    """
    if ctx is None or not ctx.transmission:
        return True
    tx = normalize_transmission(ctx.transmission)
    if not tx:
        return True
    text = f"{claim.title} {claim.rationale}"
    if tx == "manual":
        return claim.id not in auto_only_claim_ids and not claim_signals_automatic_only(text)
    if tx == "automatic":
        return not claim_signals_manual_only(text)
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


# ── Title-similarity dedup ──────────────────────────────────────────────────

_STRENGTH_RANK = {"confirmed": 0, "due": 1, "due_stated": 2, "reported": 3}
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _best_in_cluster(cluster: list[ClaimResult]) -> ClaimResult:
    """Merge a cluster of near-identical claims into one representative.

    Preserves the strongest signal across all members:
      - Severity: highest in the group
      - Strength: strongest (confirmed > due > due_stated > reported)
      - Title: from the highest-severity member (tie: highest strength rank)
      - Rationale & inspection_advice: concatenated with dedup
      - Confidence: max across members
      - Claim: the representative claim object from the chosen member
    """
    if len(cluster) == 1:
        return cluster[0]

    # Sort by severity then strength — best member first
    def _key(cr: ClaimResult) -> tuple:
        return (
            _SEVERITY_RANK.get(cr.claim.severity, 3),
            _STRENGTH_RANK.get(cr.strength, 4),
        )

    cluster.sort(key=_key)
    best = cluster[0]

    best_severity = min(
        (_SEVERITY_RANK.get(cr.claim.severity, 3) for cr in cluster),
        default=2,
    )
    best_strength = min(
        (_STRENGTH_RANK.get(cr.strength, 4) for cr in cluster),
        default=4,
    )
    severity_labels = {0: "high", 1: "medium", 2: "low"}
    strength_labels = {0: "confirmed", 1: "due", 2: "due_stated", 3: "reported"}

    # Merge rationale — unique non-overlapping sentences
    seen_rationale: list[frozenset] = []
    merged_rationale_parts = []
    for cr in cluster:
        if not cr.claim.rationale:
            continue
        # Token-length overlap guard to avoid near-duplicate paragraphs
        words = frozenset(cr.claim.rationale.lower().split())
        if any(len(words & seen) / max(len(words | seen), 1) > 0.6 for seen in seen_rationale):
            continue
        seen_rationale.append(words)
        merged_rationale_parts.append(cr.claim.rationale)

    # Merge inspection advice — unique by normalized content
    seen_advice = set()
    merged_advice_parts = []
    for cr in cluster:
        if not cr.claim.inspection_advice:
            continue
        norm = cr.claim.inspection_advice.lower().strip()
        if norm in seen_advice:
            continue
        seen_advice.add(norm)
        merged_advice_parts.append(cr.claim.inspection_advice)

    # Use the best member's claim object but patch its fields
    merged_claim = best.claim
    merged_claim.severity = severity_labels.get(best_severity, "medium")
    if merged_rationale_parts:
        merged_claim.rationale = " ".join(merged_rationale_parts)
    if merged_advice_parts:
        merged_claim.inspection_advice = "; ".join(merged_advice_parts)
    merged_claim.confidence = max(
        (cr.claim.confidence or 0.0 for cr in cluster),
        default=0.0,
    )

    return ClaimResult(claim=merged_claim, strength=strength_labels.get(best_strength, "reported"))


def _deduplicate_results(results: list[ClaimResult]) -> list[ClaimResult]:
    """Merge ClaimResults whose titles are similar (Jaccard ≥ 0.4) within the same domain.

    Fail-open: if dedup logic raises, log a warning and return the original list.
    """
    if len(results) <= 1:
        return results

    try:
        # Group by domain
        by_domain: dict[str, list[ClaimResult]] = {}
        for cr in results:
            domain = cr.claim.domain or "unknown"
            by_domain.setdefault(domain, []).append(cr)

        merged: list[ClaimResult] = []
        for domain, group in by_domain.items():
            # Within each domain, cluster by title similarity
            clusters: list[list[ClaimResult]] = []
            for cr in group:
                placed = False
                for cluster in clusters:
                    if title_similar(cluster[0].claim.title, cr.claim.title):
                        cluster.append(cr)
                        placed = True
                        break
                if not placed:
                    clusters.append([cr])

            for cluster in clusters:
                merged.append(_best_in_cluster(cluster))

        return merged

    except Exception:
        log.warning("_deduplicate_results failed — returning original list", exc_info=True)
        return results


def _servable_claims_for(variant_id: str, db: Session) -> list[Claim]:
    """Fetch claims, re-checking invariants at query time.

    Invariant: status ∈ SERVABLE_STATUSES AND is_current AND (≥1 source OR
    kind="maintenance") AND variant link AND NOT (kind!="maintenance" AND
    severity=="high" AND status unreviewed). Re-checked here, not trusted
    from the YAML/sync path. The has_source requirement drops the ungrounded
    score=0 noise (those claims are persisted with zero sources), so only
    grounded reports reach a buyer.

    Maintenance claims are exempted from BOTH has_source and the severity
    gate — their trust model is the manufacturer service interval
    (_resolve_maintenance_strength), not LLM corroboration count, so the
    "pending_human sign-off never happens" problem the severity gate exists
    for (see module docstring) doesn't apply to them the same way.
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
            or_(
                Claim.kind == "maintenance",
                not_(and_(Claim.severity == "high", Claim.status.in_(_UNREVIEWED_STATUSES))),
            ),
        )
        .all()
    )
