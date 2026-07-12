"""ground_mileage_threshold.py — deterministic mileage-onset extractor.

Populates the resolver's dormant `min_mileage_km` gate from claim text, so a
mileage-predictable failure only fires for cars that have actually reached the
onset mileage (a 30k-km car stops seeing "clutch wear by 80k"). Same family and
safety model as ground_year_window:

  * emit a threshold ONLY when the text states a km figure near an onset/wear cue
    ("wear by 80,000 km", "60 bin km sonra") — otherwise None → no gate → the
    claim shows on every car (fail-open);
  * bias LOW — take the EARLIEST mileage in a range, so the gate never hides the
    claim from a car that should still see the risk;
  * reject speeds ("20 km/h") and implausible odometer figures.

The cue and unit vocabularies are small closed sets (the allowed no-hardcoded-
data exception, like fuel types) — they do not grow with car coverage.
"""

from __future__ import annotations

import re
from typing import Callable

# How near (chars) an onset cue must sit to a km figure to ground it as a gate.
PROXIMITY = 45

# Plausible odometer-onset window; figures outside are not usable gates.
MIN_KM = 10_000
MAX_KM = 400_000

# Words marking a km figure as a FAILURE/WEAR ONSET (not an incidental mention).
_ONSET_CUES = (
    "wear", "worn", "fail", "fails", "failure", "by", "after", "around", "at",
    "from", "over", "beyond", "above", "past", "begins", "begin", "appears",
    "appear", "typically", "usually", "commonly", "common", "often", "onset",
    "degrade", "degrades", "replace", "replaced", "interval", "due",
    "sonra", "civar", "aşın", "arıza", "genellikle", "görül", "değiş",  # TR
)
_CUE_RE = re.compile(
    r"\b(?:" + "|".join(_ONSET_CUES) + r")", re.IGNORECASE | re.UNICODE
)

# Value extractors, each yielding a km integer from a match. Order matters only
# for coverage — every candidate is pooled and the minimum grounded one wins.
_PATTERNS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], int]], ...] = (
    # range "60-80k" / "60-80k km" → lower bound
    (re.compile(r"\b(\d{2,3})\s*[-–]\s*\d{2,3}\s*k(?:m)?\b", re.I),
     lambda m: int(m.group(1)) * 1000),
    # grouped thousands "80,000" / "60.000" / "150,000 km"
    (re.compile(r"\b(\d{1,3}(?:[.,]\d{3})+)\s*(?:km|kilometre|bin\s*km)?\b", re.I),
     lambda m: int(m.group(1).replace(".", "").replace(",", ""))),
    # "60 bin km" / "100 bin" (Turkish "bin" = thousand)
    (re.compile(r"\b(\d{2,3})\s*bin(?:\s*km)?\b", re.I),
     lambda m: int(m.group(1)) * 1000),
    # plain "80000 km"
    (re.compile(r"\b(\d{4,6})\s*km\b", re.I),
     lambda m: int(m.group(1))),
    # "80k" / "80 k" / "80k km"
    (re.compile(r"\b(\d{2,3})\s*k(?:m)?\b", re.I),
     lambda m: int(m.group(1)) * 1000),
)


def _is_speed(text: str, start: int, end: int) -> bool:
    """True if the figure is a speed (km/h), not an odometer reading."""
    return "km/h" in text[start:end + 3].lower()


def _has_onset_cue(text: str, start: int, end: int) -> bool:
    lo = max(0, start - PROXIMITY)
    return bool(_CUE_RE.search(text[lo:end + PROXIMITY]))


def ground_mileage_threshold(text: str | None) -> int | None:
    """Return a conservative min_mileage_km gate grounded in `text`, else None."""
    if not text:
        return None

    grounded: list[int] = []
    for pattern, to_km in _PATTERNS:
        for m in pattern.finditer(text):
            if _is_speed(text, m.start(), m.end()):
                continue
            try:
                km = to_km(m)
            except (ValueError, IndexError):
                continue
            if not (MIN_KM <= km <= MAX_KM):
                continue
            if not _has_onset_cue(text, m.start(), m.end()):
                continue
            grounded.append(km)

    return min(grounded) if grounded else None
