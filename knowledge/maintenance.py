"""Maintenance-interval detection — retag interval-shaped known_issue claims
as `kind: maintenance` so the serving ranker's `due`/`due_stated` tiers fire.

Why this exists: a timing belt, DSG fluid change, or clutch on a high-mileage
car is not a "report" — it is a maintenance item **due at an interval unless
the ad proves otherwise**. Without the retag, `_resolve_maintenance_strength`
(backend/core/resolver.py) never fires and `strength` collapses to `reported`
for ~all claims (design spec 2026-07-12, Phase C).

Candidates are detected from a CLOSED maintenance-interval vocabulary (timing
belt, DSG/mechatronic fluid, clutch, haldex fluid, spark plug, major service —
EN+TR) and the interval is derived from the claim's already-grounded
`min_mileage_km`, or grounded from the text. The vocabulary is a small closed
engineering set (the allowed no-hardcoded-car-data exception, like fuel types);
onboarding a new engine adds no entry here.

Fail-safe: a claim whose text matches the vocabulary but for which NO interval
can be derived is LEFT as known_issue. An invalid maintenance claim (no
`maintenance` block) would fail validate_part_yaml and mis-serve, so we never
emit one.

Entry points: `detect_maintenance_kind`, `build_maintenance_block`,
`to_maintenance` (used by knowledge/ledger/export.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from knowledge.ground_mileage_threshold import ground_mileage_threshold

# Plausible service-interval window in years; anything outside is not a real
# maintenance interval (rejects model years like "2014", warranty spans, etc.).
_MIN_YEARS, _MAX_YEARS = 2, 15


@dataclass(frozen=True)
class MaintenanceItem:
    """One interval-shaped maintenance category.

    `phrases`  — substrings (lowercase, EN+TR) that mark a claim as this item.
                 Deliberately require a maintenance qualifier where the bare
                 term is ambiguous (e.g. "dsg fluid", never bare "dsg", so a
                 DSG *failure* claim is not swept in).
    `evidence` — listing-description keywords that mean the service was recently
                 done, fed to _resolve_maintenance_strength as evidence_keywords
                 (returns due_stated instead of due when the ad shows one).
    `min_km` /
    `max_km`   — the plausible SERVICE-INTERVAL window for this item. The
                 interval is derived from a mileage figure grounded in the claim
                 text, but such a figure is far more often a failure *onset*
                 ("clutch squeal from 15.000 km") than a service interval. An
                 interval outside this window is therefore not an interval at
                 all, and the claim stays a known_issue. Engineering constants —
                 they do not grow with car coverage (no-hardcoded-car-data rule).
    """
    name: str
    phrases: tuple[str, ...]
    evidence: tuple[str, ...]
    min_km: int
    max_km: int


# CLOSED interval vocabulary. Order = match precedence (first hit wins).
#
# NOTE: there is deliberately no `timing_chain` entry. A chain is a lifetime
# component with no service interval — "timing chain stretch" is a known FAILURE,
# not a maintenance item, and must keep being served as a known_issue. (Treating
# it as maintenance is what turned an EA888 class-action lawsuit into a bogus
# "30.000 km timing chain service".)
MAINTENANCE_VOCAB: tuple[MaintenanceItem, ...] = (
    MaintenanceItem(
        name="timing_belt",
        phrases=(
            "timing belt", "cam belt", "cambelt", "distribution belt",
            "triger kay", "triger keme", "eksantrik kay",  # triger kayışı/kemeri
        ),
        evidence=(
            "triger değiş", "triger yeni", "triger atıl", "triger yapıl",
            "kayış değiş", "eksantrik kayış değiş",
            "timing belt changed", "timing belt replaced", "new timing belt",
            "cam belt changed", "cambelt done",
        ),
        min_km=60_000, max_km=240_000,
    ),
    MaintenanceItem(
        name="dsg_fluid",
        phrases=(
            "dsg fluid", "dsg oil", "dsg yağ", "dsg service", "dsg servis",
            "dct fluid", "dct oil", "mechatronic fluid", "mechatronic oil",
            "dual-clutch fluid", "dual clutch fluid",
            "şanzıman yağ", "gearbox oil", "gearbox fluid", "transmission fluid",
        ),
        evidence=(
            "dsg yağ değiş", "şanzıman yağ değiş", "dsg servis", "dsg service done",
            "dsg fluid changed", "transmission fluid changed",
            "gearbox oil changed", "mechatronic fluid changed",
        ),
        min_km=30_000, max_km=100_000,
    ),
    MaintenanceItem(
        name="haldex_fluid",
        phrases=(
            "haldex fluid", "haldex oil", "haldex service", "haldex yağ",
            "haldex filter",
        ),
        evidence=(
            "haldex değiş", "haldex service", "haldex fluid changed",
            "haldex yağ değiş",
        ),
        min_km=30_000, max_km=90_000,
    ),
    MaintenanceItem(
        name="spark_plug",
        phrases=("spark plug", "buji"),
        evidence=(
            "buji değiş", "buji yeni", "bujiler değiş",
            "spark plugs changed", "spark plugs replaced", "new spark plugs",
        ),
        min_km=30_000, max_km=120_000,
    ),
    MaintenanceItem(
        name="clutch",
        phrases=("clutch", "debriyaj", "kavrama"),
        evidence=(
            "debriyaj değiş", "debriyaj yeni", "kavrama değiş",
            "clutch replaced", "clutch changed", "new clutch", "clutch kit",
        ),
        # A clutch is a wear item, not a scheduled service: below ~60k a figure in
        # the text is a premature-failure report, not an interval.
        min_km=60_000, max_km=250_000,
    ),
    MaintenanceItem(
        name="major_service",
        phrases=(
            "major service", "scheduled service", "service interval",
            "büyük bakım", "periyodik bakım", "servis aralığ",
        ),
        evidence=(
            "major service done", "full service history", "büyük bakım yapıl",
            "periyodik bakım", "servis geçmiş", "tam bakım",
        ),
        min_km=10_000, max_km=40_000,
    ),
)

# "or 5 years" / "every 5 years" / "5 years or" / "5 yılda bir" — an interval
# expression, not a bare year mention (so "2014 models" is never captured).
_YEARS_RE = re.compile(
    r"(?:every|or|each|/|her)\s*(\d{1,2})\s*(?:years?|yıl|yil)"
    r"|(\d{1,2})\s*(?:years?|yıl|yil)\s*(?:or|interval|whichever|/|,)"
    r"|(\d{1,2})\s*(?:yılda|yilda)\s*bir",
    re.IGNORECASE | re.UNICODE,
)


def _claim_text(claim: dict) -> str:
    return f"{claim.get('title', '')} {claim.get('rationale', '')}"


def detect_maintenance_kind(text: str | None) -> str | None:
    """Return the maintenance-vocab category name matched in `text`, else None.

    Pure and deterministic. Matches title+rationale against the closed
    MAINTENANCE_VOCAB (first category wins). None means "not an interval-shaped
    maintenance item".
    """
    if not text:
        return None
    low = text.lower()
    for item in MAINTENANCE_VOCAB:
        if any(p in low for p in item.phrases):
            return item.name
    return None


def _item_for(name: str) -> MaintenanceItem:
    return next(i for i in MAINTENANCE_VOCAB if i.name == name)


def _ground_interval_years(text: str) -> int | None:
    """Return a service interval in years grounded in `text`, else None."""
    for m in _YEARS_RE.finditer(text):
        for g in m.groups():
            if g is None:
                continue
            years = int(g)
            if _MIN_YEARS <= years <= _MAX_YEARS:
                return years
    return None


def build_maintenance_block(claim: dict) -> tuple[str, dict] | None:
    """Non-mutating: derive (category, maintenance-block) for `claim`, or None.

    Returns None (leave as known_issue) when the claim is already maintenance,
    doesn't match the interval vocabulary, or has no derivable interval —
    the fail-safe that keeps invalid maintenance claims out of the corpus.
    """
    if claim.get("kind") == "maintenance":
        return None
    text = _claim_text(claim)
    category = detect_maintenance_kind(text)
    if category is None:
        return None

    item = _item_for(category)
    interval_km = (claim.get("applies_when") or {}).get("min_mileage_km")
    if interval_km is None:
        interval_km = ground_mileage_threshold(text)

    # Fail-safe: a figure outside the category's plausible service-interval window
    # is a failure ONSET, not an interval ("clutch squeal from 15.000 km"). Drop it
    # rather than emit a maintenance claim that would fire as DUE on every car.
    if interval_km is not None and not (item.min_km <= interval_km <= item.max_km):
        interval_km = None

    interval_years = _ground_interval_years(text)

    if interval_km is None and interval_years is None:
        return None  # fail-safe: no interval → not a servable maintenance claim

    block: dict = {}
    if interval_km is not None:
        block["interval_km"] = interval_km
    if interval_years is not None:
        block["interval_years"] = interval_years
    block["evidence_keywords"] = list(item.evidence)
    return category, block


def to_maintenance(claim: dict) -> bool:
    """Reclassify `claim` in place to kind=maintenance. Return True if changed.

    Sets `kind: maintenance` and a `maintenance` interval block. The
    `min_mileage_km` gate, if consumed as the interval, is removed (the
    maintenance serving path reads interval_km, not the applies_when gate, so
    leaving it would be a dead field). Preserves any other applies_when keys.
    Returns False (no mutation) for every non-candidate — see
    build_maintenance_block.
    """
    built = build_maintenance_block(claim)
    if built is None:
        return False
    _category, block = built

    aw = claim.get("applies_when") or {}
    if aw.get("min_mileage_km") is not None and block.get("interval_km") == aw.get("min_mileage_km"):
        aw = dict(aw)
        aw.pop("min_mileage_km", None)
        if aw:
            claim["applies_when"] = aw
        else:
            claim.pop("applies_when", None)

    claim["kind"] = "maintenance"
    claim["maintenance"] = block
    return True
