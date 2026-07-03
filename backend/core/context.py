from dataclasses import dataclass, field


@dataclass
class ListingContext:
    """Listing-level context built from ad_metadata, used for context-aware claim filtering."""
    mileage_km: int | None = None
    age_years: int | None = None
    annual_km: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None
    description: str = field(default="")  # lowercased ad text for keyword checks
    # Sahibinden "Donanım" block: {category: [feature, ...]}. None = extraction
    # found nothing at all (unknown); {} would mean "confirmed no equipment",
    # which the scraper never actually produces — treat both as "unknown".
    equipment: dict[str, list[str]] | None = None
