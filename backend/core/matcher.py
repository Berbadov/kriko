"""Variant matcher — strict, never guesses a single winner from ambiguity."""

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.normalize import (
    normalize_fuel, normalize_make, normalize_model, normalize_transmission,
)
from backend.db.models import Variant


@dataclass
class MatchResult:
    variant_ids: list[str]
    method: str      # "exact" | "ambiguous" | "no_match" | "inconsistent_listing"
    notes: str
    # True when the ad states a transmission that no matched variant is cataloged
    # with (the soft transmission filter fell back). The match still stands, but
    # gearbox-specific coverage is unknown for this config — see match_variant().
    tx_mismatch: bool = False


def match_variant(meta: dict, db: Session) -> MatchResult:
    make  = normalize_make(meta.get("make"))
    model = normalize_model(meta.get("model"))
    year  = meta.get("year")
    fuel  = normalize_fuel(meta.get("fuel_type"))
    cc    = _safe_cc(meta.get("engine_volume_cc"))
    hp    = _safe_hp(meta.get("power_hp"))
    tx    = normalize_transmission(meta.get("transmission"))

    if not make or not model or not fuel or not year:
        missing = [k for k, v in [("make", make), ("model", model), ("fuel", fuel), ("year", year)] if not v]
        return MatchResult([], "no_match", f"Missing required fields: {missing}")

    candidates = _hard_filter(db, make, model, fuel, int(year))
    if not candidates:
        return MatchResult([], "no_match", f"No {make} {model} {fuel} for {year}.")

    # If cc is provided and no candidate is even approximately plausible, the
    # listing data is inconsistent — don't guess.
    if cc and not _any_plausible_engine(candidates, cc, hp):
        return MatchResult(
            [], "inconsistent_listing",
            f"Listing (cc={cc}, hp={hp}) matches no real {make} {model} {fuel} variant.",
        )

    candidates = _narrow_by_cc(candidates, cc, tol=100)
    candidates = _narrow_by_power(candidates, hp, tol=10)
    candidates = _narrow_by_transmission(candidates, tx)

    # Listing validation: check if listing specs are consistent with the fitment
    # data (engine_family / transmission_code) for the surviving candidates.
    fitment_note = _validate_fitment_consistency(candidates, meta)

    # Ad-vs-catalog transmission contradiction: _narrow_by_transmission is a soft
    # filter that falls back to the unnarrowed set when no candidate is cataloged
    # with the ad's transmission — so the match can succeed on a variant whose
    # gearbox differs from what the ad claims. Record that honestly (the match
    # still stands; engine claims are valid) so the buyer isn't left thinking the
    # absent gearbox risks were checked. The stable `tx_coverage_gap:` note prefix
    # doubles as a catalog-gap mining signal in the analysis logs.
    tx_mismatch = bool(tx) and not any(c.transmission == tx for c in candidates)
    gap_note = _transmission_gap_note(tx, candidates) if tx_mismatch else ""

    extras = ". ".join(n for n in (fitment_note, gap_note) if n)

    if len(candidates) == 1:
        notes = f"Matched {candidates[0].id}"
        if extras:
            notes = f"{notes}. {extras}"
        return MatchResult([candidates[0].id], "exact", notes, tx_mismatch=tx_mismatch)
    if len(candidates) > 1:
        ids = [c.id for c in candidates]
        notes = f"Ambiguous among {ids}"
        if extras:
            notes = f"{notes}. {extras}"
        return MatchResult(ids, "ambiguous", notes, tx_mismatch=tx_mismatch)
    # Should not reach here (narrow functions preserve at least one candidate)
    return MatchResult([], "no_match", "Narrowing eliminated all candidates unexpectedly.")


def _transmission_gap_note(tx: str, candidates: list[Variant]) -> str:
    """Human-readable note recording an ad-vs-catalog transmission contradiction.

    `tx` is the ad's normalized transmission; `candidates` are the surviving
    matches, none of which is cataloged with it. The `tx_coverage_gap:` prefix is
    stable on purpose — it is both the source of the buyer-facing caveat and a
    greppable catalog-gap signal in logs/analyses.jsonl (CLAUDE.md's
    generalization principle: the note IS the telemetry).
    """
    cataloged = sorted({c.transmission for c in candidates if c.transmission})
    if cataloged:
        catalog_desc = "are cataloged " + " / ".join(repr(t) for t in cataloged)
    else:
        catalog_desc = "have no transmission cataloged"
    return (
        f"tx_coverage_gap: ad reports {tx!r} but matched variant(s) {catalog_desc}"
        " — gearbox-specific risks unknown for this config"
    )


# ── Fitment consistency validation ───────────────────────────────────────────

def _validate_fitment_consistency(candidates: list[Variant], meta: dict) -> str:
    """Check listing specs against variant fitment fields.

    Returns a human-readable note if the listing's engine_code or reported specs
    are inconsistent with the fitment data for all surviving candidates, or '' if OK.
    The check is advisory only — the match still proceeds.
    """
    if not candidates:
        return ""

    # If the listing provides an engine_code string (rare but possible), check it
    # against the engine_family of all candidates.
    raw_engine = (meta.get("engine_code") or "").strip().upper()
    if raw_engine:
        candidate_families = {
            (c.engine_family or "").upper() for c in candidates if c.engine_family
        }
        candidate_codes = {
            (c.engine_code or "").upper() for c in candidates if c.engine_code
        }
        if (candidate_families or candidate_codes) and raw_engine not in (candidate_families | candidate_codes):
            return (
                f"Listing engine code {raw_engine!r} does not match known fitment "
                f"for this variant — verify with seller."
            )

    return ""


# ── DB query ──────────────────────────────────────────────────────────────────

def _hard_filter(db: Session, make: str, model: str, fuel: str, year: int) -> list[Variant]:
    return (
        db.query(Variant)
        .filter(
            Variant.make == make,
            Variant.model == model,
            Variant.fuel == fuel,
            Variant.year_from <= year,
            or_(Variant.year_to == None, Variant.year_to >= year),
        )
        .all()
    )


# ── Plausibility gate ─────────────────────────────────────────────────────────

def _any_plausible_engine(
    candidates: list[Variant], cc: int | None, hp: int | None,
    cc_tol: int = 100, hp_tol: int = 25,
) -> bool:
    """True if at least one candidate could plausibly match these specs."""
    for c in candidates:
        if cc and c.displacement_cc:
            if abs(c.displacement_cc - cc) > cc_tol:
                continue
        if hp and c.power_min_hp and c.power_max_hp:
            if not (c.power_min_hp - hp_tol <= hp <= c.power_max_hp + hp_tol):
                continue
        return True
    return False


# ── Narrowing steps — each step only reduces the set, never to empty ──────────

def _narrow_by_cc(candidates: list[Variant], cc: int | None, tol: int = 100) -> list[Variant]:
    if not cc:
        return candidates
    narrowed = [
        c for c in candidates
        if c.displacement_cc and abs(c.displacement_cc - cc) <= tol
    ]
    return narrowed if narrowed else candidates


def _narrow_by_power(candidates: list[Variant], hp: int | None, tol: int = 10) -> list[Variant]:
    if not hp:
        return candidates
    narrowed = [
        c for c in candidates
        if c.power_min_hp and c.power_max_hp
        and c.power_min_hp - tol <= hp <= c.power_max_hp + tol
    ]
    return narrowed if narrowed else candidates


def _narrow_by_transmission(candidates: list[Variant], tx: str | None) -> list[Variant]:
    # Soft filter: skip if transmission unknown or if it would eliminate everything.
    if not tx:
        return candidates
    narrowed = [c for c in candidates if c.transmission and c.transmission == tx]
    return narrowed if narrowed else candidates


# ── Input sanitisers — guard against garbage from content.js ─────────────────

def _safe_cc(raw) -> int | None:
    """Return cc if it looks like a real displacement (500-8000 cc)."""
    if raw is None:
        return None
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return None
    return val if 500 <= val <= 8000 else None


def _safe_hp(raw) -> int | None:
    """Return hp if it looks like a real power output (30-600 hp).

    content.js runs numberFromText() which strips all non-digits, so
    "96 kW / 130 hp" becomes 96130 — we reject values outside [30, 600].
    """
    if raw is None:
        return None
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return None
    return val if 30 <= val <= 600 else None
