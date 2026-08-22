"""default_aftertreatment — one rule, shared by the generator and the ETL.

This existed as two implementations that had drifted: backend/sync.py's copy
was the tested one but was never called, and write_variants.py's copy was the
one that actually ran. The bug that combination hid is locked below.
"""
from backend.sync import _default_aftertreatment as sync_impl
from knowledge.catalog.emissions import default_aftertreatment
from knowledge.catalog.write_variants import _default_aftertreatment as gen_impl


def test_generator_and_etl_share_one_implementation():
    """The drift is structurally impossible now, not merely fixed."""
    assert sync_impl is default_aftertreatment
    assert gen_impl is default_aftertreatment


def test_known_diesel_always_gets_a_concrete_answer():
    """The actual bug: a euro5 diesel used to be written with no value.

    None means "unknown" and _scr_compatible fails open on it, so an SCR/AdBlue
    claim would surface on a car with no SCR hardware. A known diesel must
    never produce None.
    """
    for euro in ("euro4", "euro5", "euro6b", "euro6c", "euro6d", "euro6d_temp",
                 "", None, "something_unrecognised"):
        assert default_aftertreatment("diesel", euro) is not None, euro


def test_scr_only_for_euro6d_family():
    assert default_aftertreatment("diesel", "euro6d") == "scr"
    assert default_aftertreatment("diesel", "euro6d_temp") == "scr"
    assert default_aftertreatment("diesel", "euro6b") == "lnt"
    assert default_aftertreatment("diesel", "euro6c") == "lnt"
    assert default_aftertreatment("diesel", "euro5") == "none"


def test_unknown_fuel_is_the_only_none():
    assert default_aftertreatment(None, "euro6d") is None
    assert default_aftertreatment("", "euro6d") is None
    assert default_aftertreatment("petrol", "euro6d") == "none"
