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
    # Oil consumption / smoke — inspector sees on cold-start + road test + compression
    "oil consumption", "blue smoke", "burning oil",
    # Generic selector issues — inspector test-drives through all gears
    "difficulty selecting reverse", "cannot select reverse",
})

# Generic dashboard warning lights — true of any car, not this specific
# variant/config. A regex approach handles "ABS warning light", "ABS fault", etc.
WARNING_LIGHT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(abs|esp|epc|dpf|scr|adblue)\s*(warning|light|fault|indicator)\b", re.I),
    re.compile(r"\b(check|engine|management)\s+(light|warning)\b", re.I),
    re.compile(r"\bdashboard\s+(warning|light)\b", re.I),
    re.compile(r"\bwarning\s+light\b", re.I),
)
