"""Aftertreatment derivation — one implementation, both layers.

`aftertreatment` says what a diesel does about NOx: `scr` (AdBlue dosing),
`lnt` (a lean-NOx trap), or `none`. It scopes SCR/AdBlue claims in
backend/sync.py's _scr_compatible, so getting it wrong surfaces an AdBlue risk
on a car that has no AdBlue hardware — exactly the generic, not-config-specific
claim CLAUDE.md's product principle exists to prevent.

This lived twice: backend/sync.py derived it one way and
knowledge/catalog/write_variants.py another, with a docstring claiming they
mirrored each other. They had drifted, and the drift was invisible because only
sync.py's copy had tests — while only write_variants' copy actually ran.

It lives in the knowledge layer because dependencies flow one way: backend/ may
import knowledge/, never the reverse, so this is the only home both can share.

Closed engineering vocabulary (allowed constant per CLAUDE.md's scalability
exception) — fuel types and euro standards do not grow with car coverage.
"""

from __future__ import annotations


def default_aftertreatment(fuel: str | None, emissions: str | None) -> str | None:
    """Derive aftertreatment from fuel + euro standard.

    Returns None only when the fuel itself is unknown — that is a genuine
    "we don't know", and _scr_compatible fails open on it. A *known* diesel
    always gets a concrete answer, "none" included, so an unrecognised euro
    standard never masquerades as missing data.
    """
    f = (fuel or "").lower()
    e = (emissions or "").lower()
    if f != "diesel":
        return "none" if f == "petrol" else None
    if e.startswith("euro6d"):      # euro6d and euro6d_temp both dose AdBlue
        return "scr"
    if e in ("euro6b", "euro6c"):
        return "lnt"
    return "none"
