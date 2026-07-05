"""_transmission_compatible / _fuel_compatible / _drivetrain_compatible — a
claim's own text can rule out a variant at sync time.

Universal parts (engine, cooling, electrical, body) attach to every variant of
a model regardless of gearbox, fuel, or drivetrain. Without these checks, a
DQ200-specific claim mined from a broad "electrical" source gets broadcast to
manual variants, a diesel-only claim (e.g. "DPF blockages") mined from a
broad "body" source gets broadcast to petrol variants, and an AWD-only claim
(e.g. "Haldex AWD Coupling") gets broadcast to FWD variants — see
pipeline_postmortem. No signal in the claim's text must never exclude a
variant.
"""

from backend.sync import _drivetrain_compatible, _fuel_compatible, _transmission_compatible


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
