"""Shared claim-text transmission-mechanism signal.

Two consumers share this vocabulary so a mention of "DSG"/"mechatronic"/etc.
means the same thing on both sides:
  - sync.py's _transmission_compatible (claim <-> catalog variant grounding
    at sync time, keyed off the variant's cataloged transmission_code)
  - resolver.py's _passes_transmission_gate (claim <-> ad-stated transmission
    at serve time, keyed off what the listing itself reports)
"""

from functools import lru_cache
from pathlib import Path
import re

import yaml

AUTO_ONLY_RE = re.compile(
    r"\bdsg\b|dual[- ]clutch|mechatronic|çift kavrama|kavrama plaket|"
    r"otomatik şanzıman|kuru kavrama|wet[- ]clutch|"
    r"\btcm\b|transmission control module|"
    r"\bcvt\b|e-tech|\bhybrid\b|otomatik vites",
    re.I,
)
MANUAL_ONLY_RE = re.compile(
    r"\bclutch pedal\b|\bshift cable\b|\bmanuel vites\b|\bdebriyaj pedal",
    re.I,
)


def claim_signals_automatic_only(text: str) -> bool:
    return bool(AUTO_ONLY_RE.search(text))


def claim_signals_manual_only(text: str) -> bool:
    return bool(MANUAL_ONLY_RE.search(text))


# ── Specific-gearbox-code registry, derived from the catalog itself ─────────
#
# Used to catch a claim that names a SPECIFIC other gearbox code (a DQ200
# claim mistakenly filed under dq381.yaml) — a narrower, complementary check
# to AUTO_ONLY_RE/MANUAL_ONLY_RE's generic mechanism wording above.
#
# This used to be a hand-maintained regex
# (`dq200|dq250|dq381|dq500|dc4|dw5|dw6|edc`) — the same anti-pattern
# knowledge/stoplists.py's catalog_code_manufacturers() replaced for the
# cross-manufacturer-code guard (2026-07-05, commit 4c4c8c2): a hardcoded
# list silently misses any code added after the list was written (it also
# carried "dq500", which was never backed by a real part file, and never
# picked up "EDC7"/"EDC6"/"DSG7"/"DSG6" — real aliases already sitting in
# dw5.yaml/dw6.yaml/dq200.yaml/dq250.yaml's own known_also_as fields that the
# old regex simply didn't know about). Reading it off each transmission part
# file's own part_id + known_also_as means a newly onboarded gearbox code (or
# a newly added alias) is covered the moment its part file exists/updates —
# no separate registration step to forget.
_PARTS_TRANSMISSION_DIR = Path(__file__).resolve().parent.parent / "data" / "parts" / "transmission"
_WORD_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*\b")


@lru_cache(maxsize=1)
def _transmission_code_aliases() -> dict[str, str]:
    """alias (uppercased) -> canonical part_id (lowercased).

    Only single-word known_also_as entries (no space/hyphen, <=8 chars) are
    treated as matchable code aliases — multi-word entries like "7-speed
    DSG" or "Easy Drive Clutch" are display text, not a code someone would
    cite to name a specific *other* gearbox, so treating them as one would
    make ordinary descriptive prose look like a sibling-code mention.
    """
    aliases: dict[str, str] = {}
    if not _PARTS_TRANSMISSION_DIR.exists():
        return aliases
    for path in _PARTS_TRANSMISSION_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        part_id = data.get("part_id")
        if not part_id:
            continue
        canonical = str(part_id).lower()
        aliases[canonical.upper()] = canonical
        for alias in (data.get("known_also_as") or []):
            alias_str = str(alias).strip()
            if alias_str and " " not in alias_str and "-" not in alias_str and len(alias_str) <= 8:
                aliases[alias_str.upper()] = canonical
    return aliases


def mentioned_transmission_codes(text: str) -> set[str]:
    """Canonical transmission part_ids (lowercased) named in `text`, resolved
    through each part's own known_also_as aliases — e.g. "EDC" -> "dc4",
    "DSG7"/"7DCT" -> "dq200", "EDC6" -> "dw6".
    """
    aliases = _transmission_code_aliases()
    if not aliases:
        return set()
    tokens = {t.upper() for t in _WORD_TOKEN_RE.findall(text or "")}
    return {aliases[t] for t in tokens if t in aliases}
