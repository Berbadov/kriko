"""consequence_tier.py — deterministic priority signal for serving rank.

Maps a claim's text to high|medium|low by the failure SYSTEM it names, so the
per-listing sort can push expensive mechanical/electronic failures above comfort
and cosmetic ones ACROSS a whole car (engine + transmission + electrical + body).

It failed as a *within-engine* discriminator (every engine claim names an engine
system) — it is used here only as a *cross-car* ranking input, one term in the
priority key, never as a gate.

Safety (asymmetric, like ground_year_window / ground_mileage_threshold):
  * an expensive-subsystem term always wins → HIGH (never demoted by a
    co-occurring comfort word like "noise");
  * demotion to LOW happens only on an UNAMBIGUOUS comfort/cosmetic/performance
    term and no high term — never on ambiguous words like "software"
    (infotainment vs. ECU), which fall through to MEDIUM;
  * default MEDIUM — an unclassified claim is never buried.

Vocabularies are small, closed engineering categories (the allowed no-hardcoded-
data exception, like fuel types) and multilingual (EN + TR) so terms like
`mekatronik` / `enjektör` are not missed and silently demoted.

Matching: multi-word/long terms are START-anchored (`\\bturbo` matches
"turbocharger", `\\benjektör` matches the Turkish-inflected "enjektörü"); short
abbreviations use FULL word boundaries (`\\bscr\\b`) so they never match inside
words like "screen".
"""

from __future__ import annotations

import re

# Expensive / high-consequence subsystem categories (EN + TR).
_HIGH_WORDS = (
    "timing belt", "timing chain", "cam belt", "chain tensioner", "zahnriemen",
    "triger", "timing", "mechatronic", "mekatronik", "mechatronik",
    "dual clutch", "dual-clutch", "clutch pack", "kavrama", "control unit",
    "control module", "particulate filter", "partikül", "adblue", "catalytic",
    "katalitik", "turbocharger", "turboşarj", "turbo", "wastegate",
    "supercharger", "injector", "injection", "enjektör", "common rail",
    "fuel pump", "yakıt pompası", "high pressure fuel", "head gasket",
    "silindir kapağı", "piston", "bearing", "rulman", "crankshaft", "krank",
    "camshaft", "eksantrik", "conrod", "cylinder", "valve", "supap",
    "flywheel", "dual-mass", "dual mass", "volant",
    "oil consumption", "yağ tüketimi", "oil pump", "yağ pompası", "water pump",
    "devirdaim", "overheat", "hararet", "hybrid", "high voltage", "inverter",
)
_HIGH_ABBR = (
    "egr", "scr", "dpf", "dsg", "dct", "ecu", "ecm", "tcm", "tcu", "edc",
    "nox", "hpfp", "48v", "hv",
)

# Unambiguous comfort / cosmetic / performance / infotainment terms (EN + TR).
_LOW_WORDS = (
    "infotainment", "radio", "audio", "speaker", "hoparlör", "bluetooth",
    "navigation", "touchscreen", "carplay", "android auto", "head unit",
    "rattle", "squeak", "creak", "gıcırtı", "wind noise", "road noise",
    "upholstery", "döşeme", "armrest", "cup holder", "paint", "boya",
    "scratch", "çizik", "stone chip", "cosmetic", "trim piece", "stain", "leke",
    "acceleration", "fuel economy", "yakıt ekonomisi", "top speed",
    "horsepower", "power-to-weight",
)
_LOW_ABBR = ("usb",)


def _words_re(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")",
                      re.IGNORECASE | re.UNICODE)


def _abbr_re(abbr: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(a) for a in abbr) + r")\b",
                      re.IGNORECASE | re.UNICODE)


_HIGH_WORDS_RE = _words_re(_HIGH_WORDS)
_HIGH_ABBR_RE = _abbr_re(_HIGH_ABBR)
_LOW_WORDS_RE = _words_re(_LOW_WORDS)
_LOW_ABBR_RE = _abbr_re(_LOW_ABBR)


def consequence_tier(title: str, rationale: str) -> str:
    """Return "high" | "medium" | "low" for a claim's failure system."""
    text = f"{title or ''} {rationale or ''}"
    if _HIGH_WORDS_RE.search(text) or _HIGH_ABBR_RE.search(text):
        return "high"
    if _LOW_WORDS_RE.search(text) or _LOW_ABBR_RE.search(text):
        return "low"
    return "medium"
