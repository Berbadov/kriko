"""ground_year_window.py — deterministic grounding guard for model-year windows.

A proposed model-year window (`applies_year_from` / `applies_year_to`) removes a
claim from the served output for cars *outside* the window. That is a silent
suppression, so before such a window is trusted it must be grounded in the cited
source text — this guard is the deterministic check that sits in front of any
LLM/upstream that proposes one (same family as `mentions_sibling_code`,
`_fuel_grounded_variants`: narrow only on a confident signal, stay broad
otherwise).

A bound `Y` is grounded iff BOTH hold in the source:
  1. the exact year token appears (word-boundaried, so 2022 does not match inside
     a part number like 20225), AND
  2. a direction-appropriate cue word sits within PROXIMITY chars of that token
     (lower bound → "from/since/affects…"; upper bound → "fixed/until/revised…").

An ungrounded bound is DROPPED (set to None → open on that side). Dropping only
ever widens the window (shows the claim to *more* cars), the fail-open-safe
direction — so a hallucinated bound can never narrow the window past the
evidence. Feed this the LLM's own cited quote, not the whole document, for the
tightest precision.

The cue lists are small, closed engineering vocabularies (like fuel types) — the
allowed exception to the no-hardcoded-car-data rule: they do not grow with car
coverage, so no per-model registration is ever needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# How near (in characters) a cue word must sit to a year token to ground it.
PROXIMITY = 40

# Cue words that mark a year as the START of a defect window (lower bound).
LOWER_CUES = (
    "from", "since", "starting", "onward", "onwards", "introduced",
    "began", "begins", "affects", "affecting",
    "itibaren", "başlayan", "sonrası",  # TR: from / starting / after
)

# Cue words that mark a year as the END of a defect window (upper bound) — i.e.
# the defect was resolved by/at that year.
UPPER_CUES = (
    "fixed", "resolved", "corrected", "solved", "until", "through",
    "revised", "addressed", "eliminated", "improved", "kadar",
    "giderildi", "çözüldü", "düzeltildi",  # TR: fixed / resolved / corrected
)


def _cue_pattern(cues: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        r"\b(?:" + "|".join(re.escape(c) for c in cues) + r")\b",
        re.IGNORECASE | re.UNICODE,
    )


_LOWER_RE = _cue_pattern(LOWER_CUES)
_UPPER_RE = _cue_pattern(UPPER_CUES)


@dataclass
class WindowGrounding:
    """Sanitized window plus a per-bound audit trail.

    `year_from` / `year_to` are the safe-to-serve bounds (None where the proposed
    bound was not grounded). `report` maps "from"/"to" → "kept" or a
    "dropped: …" reason, for the human-review UI; a bound that was not proposed
    (input None) has no entry.
    """

    year_from: int | None
    year_to: int | None
    report: dict[str, str]


def _is_grounded(year: int, source: str, cue_re: re.Pattern[str]) -> bool:
    token_re = re.compile(r"\b" + str(year) + r"\b")
    for m in token_re.finditer(source):
        lo = max(0, m.start() - PROXIMITY)
        hi = m.end() + PROXIMITY
        if cue_re.search(source[lo:hi]):
            return True
    return False


def ground_year_window(
    year_from: int | None,
    year_to: int | None,
    source_text: str | None,
) -> WindowGrounding:
    """Drop any proposed bound not grounded in `source_text`; keep the rest."""
    source = source_text or ""
    report: dict[str, str] = {}

    out_from: int | None = None
    if year_from is not None:
        if _is_grounded(year_from, source, _LOWER_RE):
            out_from = year_from
            report["from"] = "kept"
        else:
            report["from"] = f"dropped: no lower-bound cue near {year_from}"

    out_to: int | None = None
    if year_to is not None:
        if _is_grounded(year_to, source, _UPPER_RE):
            out_to = year_to
            report["to"] = "kept"
        else:
            report["to"] = f"dropped: no upper-bound cue near {year_to}"

    return WindowGrounding(out_from, out_to, report)
