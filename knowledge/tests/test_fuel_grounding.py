"""Fuel-aware grounding — a fuel-specific claim must not ground to other fuels.

A K9K (diesel) injector claim grounding to a petrol variant would show a buyer a
wrong-fuel issue. Narrowing happens ONLY on a clear fuel signal; fuel-agnostic
claims (A/C, electrical) stay broad.
"""

from knowledge.extract import CandidateClaim
from knowledge.promote import _claim_fuel, _fuel_grounded_variants


def _claim(title, hint=None, quote=""):
    return CandidateClaim(
        title=title, domain="engine", severity="high",
        rationale="r", inspection_advice="a", quote=quote,
        engine_or_variant_hint=hint,
    )


FUELS = {
    "m_h5f": "petrol", "m_h5h": "petrol",
    "m_k9k": "diesel", "m_r9m": "diesel",
}
VIDS = list(FUELS)


def test_diesel_claim_grounds_only_to_diesel():
    c = _claim("Injector failure", hint="K9K", quote="K9K enjektör")
    assert _claim_fuel(c) == "diesel"
    assert set(_fuel_grounded_variants(VIDS, c, FUELS)) == {"m_k9k", "m_r9m"}


def test_petrol_claim_grounds_only_to_petrol():
    c = _claim("Turbo failure", hint="1.3 TCe")
    assert _claim_fuel(c) == "petrol"
    assert set(_fuel_grounded_variants(VIDS, c, FUELS)) == {"m_h5f", "m_h5h"}


def test_adblue_is_diesel():
    c = _claim("AdBlue pump failure", quote="AdBlue sistemi arızası")
    assert _claim_fuel(c) == "diesel"


def test_no_signal_grounds_broadly():
    c = _claim("A/C condenser leak", quote="klima radyatörü")
    assert _claim_fuel(c) is None
    assert _fuel_grounded_variants(VIDS, c, FUELS) == VIDS


def test_ambiguous_both_fuels_grounds_broadly():
    # Mentions both a diesel and petrol code → no confident narrowing.
    c = _claim("Engine issue", hint="K9K or H5H", quote="K9K and TCe")
    assert _claim_fuel(c) is None
    assert _fuel_grounded_variants(VIDS, c, FUELS) == VIDS


def test_no_fuel_map_falls_back_to_broad():
    c = _claim("Injector failure", hint="K9K")
    assert _fuel_grounded_variants(VIDS, c, None) == VIDS
