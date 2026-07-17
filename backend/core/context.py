from dataclasses import dataclass, field


@dataclass
class ListingContext:
    """Listing-level context built from ad_metadata, used for context-aware claim filtering."""
    mileage_km: int | None = None
    age_years: int | None = None
    # Raw listing model year (kept alongside the derived age_years, which loses it).
    # Used by the claim model-year window gate. Year is the finest granularity a
    # Sahibinden listing exposes — no month/registration date.
    model_year: int | None = None
    annual_km: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    description: str = field(default="")  # lowercased ad text for keyword checks
    # Sahibinden "Donanım" block: {category: [feature, ...]}. None = extraction
    # found nothing at all (unknown); {} would mean "confirmed no equipment",
    # which the scraper never actually produces — treat both as "unknown".
    equipment: dict[str, list[str]] | None = None
