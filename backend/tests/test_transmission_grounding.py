"""_transmission_compatible / _fuel_compatible / _drivetrain_compatible /
_powertrain_compatible — a claim's own text can rule out a variant at sync time.

Universal parts (engine, cooling, electrical, body) attach to every variant of
a model regardless of gearbox, fuel, or drivetrain. Without these checks, a
DQ200-specific claim mined from a broad "electrical" source gets broadcast to
manual variants, a diesel-only claim (e.g. "DPF blockages") mined from a
broad "body" source gets broadcast to petrol variants, and an AWD-only claim
(e.g. "Haldex AWD Coupling") gets broadcast to FWD variants — see
pipeline_postmortem. No signal in the claim's text must never exclude a
variant.

_powertrain_compatible regression: megane4_elec.yaml and clio5_elec.yaml (both
universal electrical parts) absorbed Megane E-Tech Electric / E-Tech Hybrid
content (heat pump, DC/AC charging, "battery charging impossible") and served
it on plain petrol/diesel variants — including manual cars, i.e. exactly
"automatic transmission issues on a manual car" from the buyer's point of
view, except the actual defect is a powertrain-type mismatch (EV/hybrid
hardware on an ICE-only car), not just a gearbox mismatch. 2026-07-05.
"""

from backend.sync import (
    _drivetrain_compatible, _fuel_compatible, _powertrain_compatible, _transmission_compatible,
)


def _claim(title="", rationale=""):
    return {"title": title, "rationale": rationale}


def test_no_signal_grounds_broadly():
    c = _claim("12V battery drain", "The battery drains overnight on some units.")
    assert _transmission_compatible(c, "manual")
    assert _transmission_compatible(c, "dq200")


def test_dsg_specific_claim_excluded_from_manual():
    c = _claim("DSG7 (DQ200) mechatronics failure risk", "DQ200 mechatronics unit wears.")
    assert not _transmission_compatible(c, "manual")


def test_named_code_only_grounds_that_code():
    c = _claim("DQ200 valve body cracking", "The DQ200 mechatronic valve body cracks.")
    assert _transmission_compatible(c, "dq200")
    assert not _transmission_compatible(c, "dq250")
    assert not _transmission_compatible(c, "manual")


def test_claim_naming_both_codes_grounds_both():
    c = _claim("DQ200/DQ250 dry-clutch shudder", "Affects both DQ200 and DQ250 units.")
    assert _transmission_compatible(c, "dq200")
    assert _transmission_compatible(c, "dq250")
    assert not _transmission_compatible(c, "manual")


def test_generic_dsg_term_excluded_from_manual_even_without_code():
    c = _claim("DSG gearbox hesitation or rough shifting", "Chronic hesitation in the DSG.")
    assert not _transmission_compatible(c, "manual")
    assert _transmission_compatible(c, "dq200")


def test_tcm_claim_excluded_from_manual():
    c = _claim(
        "Chronic TCM Communication Failure",
        "The Transmission Control Module fails to communicate with the data bus.",
    )
    assert not _transmission_compatible(c, "manual")


def test_clutch_pedal_claim_excluded_from_dsg():
    c = _claim(
        "Chronic idling vibrations",
        "Linked to the flywheel/clutch pedal connection, worsened by pedal adjustment.",
    )
    assert _transmission_compatible(c, "manual")
    assert not _transmission_compatible(c, "dq250")


def test_fuel_no_signal_grounds_broadly():
    c = _claim("Paint chipping on front bumper", "Thin body panels prone to chips.")
    assert _fuel_compatible(c, "petrol")
    assert _fuel_compatible(c, "diesel")


def test_diesel_specific_claim_excluded_from_petrol():
    c = _claim("DPF blockages (TDI models)", "R9M 1.6 dCi engines prone to DPF clogging.")
    assert _fuel_compatible(c, "diesel")
    assert not _fuel_compatible(c, "petrol")


def test_petrol_specific_claim_excluded_from_diesel():
    c = _claim("TSI carbon buildup", "1.4 TCe direct-injection engines foul intake valves.")
    assert _fuel_compatible(c, "petrol")
    assert not _fuel_compatible(c, "diesel")


def test_fuel_claim_naming_both_grounds_both():
    c = _claim("AC compressor failures", "Affects both TSI and TDI engined Golfs alike.")
    assert _fuel_compatible(c, "petrol")
    assert _fuel_compatible(c, "diesel")


def test_drivetrain_no_signal_grounds_broadly():
    c = _claim("12V battery drain", "The battery drains overnight on some units.")
    assert _drivetrain_compatible(c, "fwd")
    assert _drivetrain_compatible(c, "awd")


def test_haldex_awd_claim_excluded_from_fwd():
    c = _claim(
        "Haldex AWD Coupling Oil Degradation (Golf R)",
        "The Golf R's Haldex AWD system requires oil changes every 40,000 km "
        "to prevent pump failure.",
    )
    assert not _drivetrain_compatible(c, "fwd")
    assert _drivetrain_compatible(c, "awd")


def test_drivetrain_unknown_variant_grounds_broadly():
    """Missing drivetrain on the variant side (None) never excludes — mirrors
    _fuel_compatible/_transmission_compatible's no-signal-means-broad rule."""
    c = _claim("4Motion coupling wear", "Quattro-style AWD coupling wears over time.")
    assert _drivetrain_compatible(c, None)


def test_rwd_specific_claim_excluded_from_fwd():
    c = _claim("Rear-wheel drive propshaft vibration", "Common on RWD models above 100k km.")
    assert not _drivetrain_compatible(c, "fwd")
    assert _drivetrain_compatible(c, "rwd")


def test_powertrain_no_signal_grounds_broadly():
    c = _claim("12V battery drain", "The battery drains overnight on some units.")
    assert _powertrain_compatible(c, "petrol")
    assert _powertrain_compatible(c, "diesel")


def test_etech_gearbox_claim_excluded_from_ice_variant():
    # Live regression: clio5_elec.yaml, served on manual H4D/H5D Clio 5 variants.
    c = _claim(
        "E-Tech Gearbox Hesitations and Jerky Transitions (Hybrid models)",
        "The E-Tech hybrid gearbox exhibits hesitation and jerky transitions in hot weather.",
    )
    assert not _powertrain_compatible(c, "petrol")
    assert not _powertrain_compatible(c, "diesel")


def test_dc_charging_claim_excluded_from_ice_variant():
    # Live regression: megane4_elec.yaml, served on K9K diesel Megane 4 variants —
    # DC charging/preconditioning is EV-only vocabulary, meaningless on a plain diesel.
    c = _claim(
        "DC charging power collapse in winter without preconditioning",
        "The traction battery fails to precondition before DC fast charging in cold weather.",
    )
    assert not _powertrain_compatible(c, "diesel")


def test_heat_pump_charging_claim_excluded_from_ice_variant():
    c = _claim(
        "Heat pump insulation fault causing charging aborts",
        "Early Megane E-Tech models suffer from a heat-pump insulation defect "
        "that prevents charging entirely.",
    )
    assert not _powertrain_compatible(c, "petrol")


def test_genuine_ice_claim_not_excluded():
    c = _claim("Turbo actuator malfunctions (K9K 820)", "The variable-geometry turbo actuator sticks.")
    assert _powertrain_compatible(c, "diesel")
    assert _powertrain_compatible(c, "petrol")


def test_generic_hybrid_word_excludes_manual_via_transmission_axis_too():
    # Belt-and-suspenders: the same claim is also caught by the widened
    # _AUTO_ONLY_RE on the transmission axis (tc == "manual").
    from backend.sync import _transmission_compatible

    c = _claim(
        "E-Tech Gearbox Hesitations and Jerky Transitions (Hybrid models)",
        "The E-Tech hybrid gearbox exhibits hesitation and jerky transitions in hot weather.",
    )
    assert not _transmission_compatible(c, "manual")


def test_cvt_claim_excluded_from_manual_via_transmission_axis():
    c = _claim("CVT gearbox jerks and delayed responses", "Older CVT gearboxes suffer from jerky shifts.")
    assert not _transmission_compatible(c, "manual")
