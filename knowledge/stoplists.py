"""Curated stoplists for the inspection-value gate.

These lists are used by gate_inspection_value in judge.py to quickly reject
claims that a standard pre-purchase mechanic inspection already covers, or
generic dashboard warning lights that are true of any car.
"""

import re

# Items a standard pre-purchase mechanic inspection (ekspertiz) covers as routine.
# A claim matching any of these keywords is low value by the CLAUDE.md principle.
INSPECTION_COVERED: frozenset[str] = frozenset({
    # Fluids (inspector checks all fluid levels)
    "brake fluid", "coolant level", "oil level", "power steering fluid",
    "transmission fluid", "fluid level",
    # Brake wear (inspector measures pad/disc thickness)
    "brake pad", "brake disc", "brake rotor", "brake wear",
    # Injector bench tests (diesel specialist routine)
    "injector cleaning", "injector test", "injector bench", "injector flow test",
    # Compression (mechanic checks with gauge)
    "compression test",
    # Tire wear (visual inspection)
    "tire wear", "tyre wear",
    # Steering/suspension play (inspector checks all joints)
    "ball joint", "track rod", "tie rod", "wheel bearing play",
    # Clutch and manual gearbox (inspector test-drives — all caught on the road)
    "clutch wear", "clutch slip", "clutch drag", "synchro wear",
    "difficulty engaging gear", "grinding noise", "stuck in gear",
    "leaking gearbox oil", "gearbox oil leak",
    "selector fork", "synchromesh",
    # Exhaust visual (inspector checks for leaks/damage)
    "exhaust leak", "exhaust corrosion",
    # Generic gearbox symptoms (inspector test-drive catches these)
    "jerking in gear", "dropping out of gear", "burning smell from gearbox",
    # Generic system categories — too vague to act on; inspector covers these
    "brake system failure", "suspension failure", "steering system malfunction",
    "engine mounting", "engine mount",
    # Generic selector issues — inspector test-drives through all gears
    "difficulty selecting reverse", "cannot select reverse",
})

# "Oil consumption" / "blue smoke" / "burning oil" describe BOTH the routine
# dipstick-and-road-test check every used car needs AND well-documented,
# mileage-specific chronic defects in particular engine families (e.g. VW
# EA111/EA211 1.4 TSI/TFSI piston-ring oil consumption, addressed by extended
# warranty campaigns) — exactly the config-specific, mileage-predictable risk
# CLAUDE.md wants surfaced. An unconditional keyword reject killed the latter
# alongside the former. The LLM alone doesn't reliably separate them either —
# tested empirically, it defaulted to "keep everything" once the keyword
# pre-reject was removed, including deliberately generic filler claims with no
# engine reference at all. So: fast-reject only when NO specificity signal
# (engine/transmission code, displacement+fuel-tech label, or an explicit
# mileage figure) accompanies the term — that signal is itself the evidence
# this is config/mileage-specific rather than generic used-car advice.
AMBIGUOUS_INSPECTION_TERMS: frozenset[str] = frozenset({
    "oil consumption", "blue smoke", "burning oil",
})

# Engine/transmission code tokens (EA211, DQ200, K9K, H5H, R9M, DC4, ...): 1-4
# letters, a digit, then up to 3 more alphanumerics. Matches every code format
# used in this catalog's variant descriptors. Shared by promote.py's deterministic
# gate_variant bypass and has_specificity_signal below.
CODE_TOKEN_RE = re.compile(r"\b[A-Za-z]{1,4}\d[A-Za-z0-9]{0,3}\b")
_DISPLACEMENT_RE = re.compile(r"\b\d\.\d\s*(tsi|tdi|tfsi|dci|tce|sce|hdi|vti)\b", re.I)
_MILEAGE_RE = re.compile(r"\b\d[\d,.]*\s*(km|kilomet|mile|mi)\b", re.I)


def code_tokens(text: str) -> set[str]:
    """Uppercased engine/transmission code tokens found in text (EA211, DQ200, ...)."""
    return {t.upper() for t in CODE_TOKEN_RE.findall(text or "")}


def has_specificity_signal(text: str) -> bool:
    """True if text names a specific engine/transmission code (EA211, DQ200, K9K),
    a displacement+fuel-tech label (e.g. "1.4 TSI"), or an explicit mileage
    figure — i.e. it plausibly describes a config- or mileage-specific claim
    rather than generic used-car advice.
    """
    return bool(
        CODE_TOKEN_RE.search(text)
        or _DISPLACEMENT_RE.search(text)
        or _MILEAGE_RE.search(text)
    )

# Generic dashboard warning lights — true of any car, not this specific
# variant/config. A regex approach handles "ABS warning light", "ABS fault", etc.
WARNING_LIGHT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(abs|esp|epc|dpf|scr|adblue)\s*(warning|light|fault|indicator)\b", re.I),
    re.compile(r"\b(check|engine|management)\s+(light|warning)\b", re.I),
    re.compile(r"\bdashboard\s+(warning|light)\b", re.I),
    re.compile(r"\bwarning\s+light\b", re.I),
)
