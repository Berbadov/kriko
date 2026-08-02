"""_scr_compatible / _default_aftertreatment -- AdBlue/SCR variant scoping (B11).

An AdBlue claim links to aftertreatment="scr" variants; does NOT link to a
non-SCR (lnt/none) diesel variant nor a petrol variant; a claim with no SCR
signal still grounds broadly regardless of aftertreatment; a variant with
aftertreatment=None grounds broadly.
"""

import pytest

from backend.sync import _scr_compatible, _default_aftertreatment


def _claim(title: str, rationale: str = "") -> dict:
    return {"title": title, "rationale": rationale}


# -- _scr_compatible --

def test_adblue_claim_excluded_from_lnt_variant():
    c = _claim("AdBlue pump failure", "The AdBlue/SCR urea pump fails on K9K Blue dCi")
    assert not _scr_compatible(c, "lnt")


def test_adblue_claim_excluded_from_none_variant():
    c = _claim("AdBlue tank leak", "Urea tank develops cracks")
    assert not _scr_compatible(c, "none")


def test_adblue_claim_links_to_scr_variant():
    c = _claim("SCR catalyst degradation", "The SCR catalyst loses efficiency")
    assert _scr_compatible(c, "scr")


def test_adblue_claim_broad_when_variant_unknown():
    c = _claim("AdBlue injector clogged", "DEF injector blocks periodically")
    assert _scr_compatible(c, None)


def test_non_scr_claim_broad_regardless_of_aftertreatment():
    c = _claim("Timing belt wear", "The timing belt stretches after 100k km")
    assert _scr_compatible(c, "lnt")
    assert _scr_compatible(c, "scr")
    assert _scr_compatible(c, "none")
    assert _scr_compatible(c, None)


def test_dpf_claim_is_not_scr_signal():
    """DPF is fuel-compatible (diesel) but not SCR-specific."""
    c = _claim("DPF regeneration failure", "DPF blocks on short-trip driving")
    assert _scr_compatible(c, "lnt")
    assert _scr_compatible(c, "scr")


# -- _default_aftertreatment --

def test_petrol_is_none():
    assert _default_aftertreatment("petrol", "euro6d") == "none"
    assert _default_aftertreatment("petrol", None) == "none"


def test_diesel_euro6d_is_scr():
    assert _default_aftertreatment("diesel", "euro6d") == "scr"
    assert _default_aftertreatment("diesel", "euro6d_temp") == "scr"


def test_diesel_euro6b_is_lnt():
    assert _default_aftertreatment("diesel", "euro6b") == "lnt"
    assert _default_aftertreatment("diesel", "euro6c") == "lnt"


def test_diesel_unknown_emissions_is_none():
    assert _default_aftertreatment("diesel", None) == "none"
    assert _default_aftertreatment("diesel", "euro5") == "none"


def test_unknown_fuel_returns_none():
    assert _default_aftertreatment(None, "euro6d") is None
    assert _default_aftertreatment("", "euro6d") is None
