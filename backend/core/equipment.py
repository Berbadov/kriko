"""Shared equipment-tag vocabulary for listing-equipment gating (Phase 4).

Two consumers share this vocabulary so a tag means the same thing on both
sides of the gate:
  - sync.py auto-derives `Claim.requires_equipment` from the claim's own
    (English) title/rationale text — no hand-authored YAML tagging needed,
    mirroring the transmission/fuel text-sniffing precedent.
  - resolver.py checks a listing's (mostly Turkish) scraped `equipment` dict
    against the same tags at serving time.

Keep patterns tight (prefer terms that are unambiguous equipment names) —
a claim that merely mentions a term in passing shouldn't get hidden from
every car that lacks the option.
"""

import re

EQUIPMENT_TAGS: dict[str, re.Pattern] = {
    "sunroof": re.compile(
        r"sunroof|moonroof|panoramik?\s*(?:cam\s*)?tavan|panoramic\s*(?:roof|sunroof)|cam\s*tavan",
        re.I,
    ),
}


def derive_equipment_tags(text: str) -> list[str]:
    """Return the equipment tags a claim's own text signals, e.g. ["sunroof"]."""
    return [tag for tag, pattern in EQUIPMENT_TAGS.items() if pattern.search(text)]


def listing_has_equipment(tag: str, equipment: dict[str, list[str]]) -> bool:
    """Does the listing's scraped equipment dict mention this tag?"""
    pattern = EQUIPMENT_TAGS.get(tag)
    if pattern is None:
        return False
    return any(
        pattern.search(item)
        for items in equipment.values()
        for item in items
    )
