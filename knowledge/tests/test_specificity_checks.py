"""New deterministic quality checks added 2026-07-04 per user feedback:
"data quality and mismatches are horrible... not P0312 fail may cause x, we
need just injector problems with brief descriptions. Do harder benchmarks."
"""

from unittest.mock import patch

from knowledge.stoplists import (
    has_variant_anchor,
    title_has_dtc_code,
    title_is_verbose,
)
from knowledge.judge import gate_generic


def test_title_has_dtc_code_detects_standard_and_extended_codes():
    assert title_has_dtc_code("Mechatronics adaptation not completed (P1781/18189)")
    assert title_has_dtc_code("Transmission Overheating (P17F0/006128)")
    assert title_has_dtc_code("P0300 Random/Multiple Cylinder Misfire")


def test_title_has_dtc_code_ignores_clean_title():
    assert not title_has_dtc_code("Chronic injector fouling (K9K 1.5 dCi)")


def test_title_is_verbose_catches_paragraph_titles():
    long_title = (
        "Customers with 2.0 TDI Pump-Düse (PD) engines—particularly those rated "
        "at 170 horsepower and some 140 horsepower models—are experiencing "
        "frequent and repeated failures of the fuel injectors."
    )
    assert title_is_verbose(long_title)


def test_title_is_verbose_allows_normal_titles():
    assert not title_is_verbose("Chronic injector fouling (K9K 1.5 dCi)")


def test_has_variant_anchor_true_for_engine_code():
    assert has_variant_anchor("Chronic injector fouling (K9K 1.5 dCi)")


def test_has_variant_anchor_true_for_displacement_label():
    assert has_variant_anchor("Injector fouling on 1.5 dCi engines")


def test_has_variant_anchor_false_for_bare_generic():
    assert not has_variant_anchor("Injector problems")


def test_has_variant_anchor_excludes_dtc_codes():
    # A DTC code matches the same loose code-token shape as an engine code
    # (letters+digit+alnum) — must NOT count as a variant anchor, or a
    # DTC-litany title would look "specific" when it's actually the opposite.
    assert not has_variant_anchor("Mechatronics adaptation not completed (P1781/18189)")


def test_gate_generic_fast_rejects_textbook_trivial_claim():
    # Regression: ministral-8b answered "keep" here while its own stated
    # reason said the opposite ("...relevant to any car buyer regardless of
    # model specificity") — don't trust the LLM on this clear-cut case.
    result = gate_generic(
        "Regular oil changes prevent engine wear",
        "Not changing oil causes engine wear in all cars.",
    )
    assert result.passed is False
    assert "fast-reject" in result.reason


@patch("knowledge.judge.MISTRAL_API_KEY", "dummy-key-for-test")
@patch("knowledge.judge._ask", return_value=(False, "mocked: config-specific, keep"))
def test_gate_generic_escape_valve_keeps_config_specific_oil_claim(_ask):
    # Same generic-sounding phrasing, but with an engine code present — must
    # NOT be fast-rejected before the LLM even runs (same escape-valve design
    # as AMBIGUOUS_INSPECTION_TERMS/has_specificity_signal). Falling through
    # to _ask (mocked here) proves the fast pre-check didn't short-circuit it.
    result = gate_generic(
        "Regular oil changes prevent premature wear (K9K 1.5 dCi)",
        "K9K injectors require more frequent oil changes due to fouling.",
    )
    assert _ask.called
    assert "fast-reject" not in result.reason
