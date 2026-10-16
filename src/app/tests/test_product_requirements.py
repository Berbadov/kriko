"""Behavior tests for conservative numeric requirement matching."""

from app.requirements import evaluate_requirement


def test_extreme_finite_measurement_cannot_abort_requirement_evaluation():
    result = evaluate_requirement("voltage under 9 V", [_fact("voltage", "1e1000000", "V")])
    assert result == {"status": "unknown", "evidence": "", "source": ""}


def test_symbol_case_does_not_conflate_different_measurement_scales():
    cases = [
        ("voltage under 2 mV", _fact("voltage", "1", "MV")),
        ("frequency over 1 kHz", _fact("frequency", "1", "mHz")),
        ("capacity at least 8 GB", _fact("capacity", "8", "Gb")),
    ]
    for phrase, fact in cases:
        assert evaluate_requirement(phrase, [fact]) == {
            "status": "unknown", "evidence": "", "source": ""}


def _fact(key: str, value: str, unit: str, *, identity: bool = False) -> dict:
    return {"text": f"{key} {value} {unit}".strip(), "key": key, "value": value,
            "unit": unit, "identity": identity, "source": "https://example.test/spec"}


def test_strict_upper_bound_converts_compatible_units():
    result = evaluate_requirement("weight under 2 kg", [_fact("weight", "1500", "g")])
    assert result == {"status": "met", "evidence": "weight 1500 g",
                      "source": "https://example.test/spec"}


def test_strict_bound_does_not_accept_equality():
    result = evaluate_requirement("weight less than 2 kg", [_fact("weight", "2000", "g")])
    assert result == {"status": "unknown", "evidence": "", "source": ""}


def test_inclusive_bound_accepts_equality():
    result = evaluate_requirement("voltage at least 18 V", [_fact("voltage_v", "18000", "mV")])
    assert result and result["status"] == "met"
    assert result["evidence"] == "voltage_v 18000 mV"


def test_no_more_than_is_inclusive_not_negation():
    result = evaluate_requirement("weight no more than 2 kg", [_fact("weight", "2", "kg")])
    assert result and result["status"] == "met"


def test_bare_measurement_requires_one_exact_compatible_fact():
    result = evaluate_requirement("18V", [_fact("voltage_v", "18", "V")])
    assert result and result["status"] == "met"
    assert evaluate_requirement("18V", [_fact("voltage_v", "20", "V")]) == {
        "status": "unknown", "evidence": "", "source": ""}


def test_signed_numeric_constraints_are_not_interpreted_as_unsigned():
    positive = [_fact("voltage", "2", "V")]
    assert evaluate_requirement("voltage under -2 V", positive) == {
        "status": "unknown", "evidence": "", "source": ""}
    assert evaluate_requirement("-18V", [_fact("voltage", "18", "V")]) == {
        "status": "unknown", "evidence": "", "source": ""}


def test_nonfinite_fact_values_are_unknown():
    for value in ("NaN", "Infinity", "-Infinity"):
        assert evaluate_requirement("voltage under 9 V", [_fact("voltage", value, "V")]) == {
            "status": "unknown", "evidence": "", "source": ""}


def test_unrecognized_field_qualifiers_cannot_match_by_one_shared_word():
    assert evaluate_requirement("voltage different from 18V", [
        _fact("voltage", "18", "V")
    ]) == {"status": "unknown", "evidence": "", "source": ""}


def test_symbolic_strict_lower_bound_converts_units():
    result = evaluate_requirement("current > 500 mA", [_fact("current", "0.6", "A")])
    assert result and result["status"] == "met"


def test_symbolic_inclusive_upper_bound_accepts_equality():
    result = evaluate_requirement("voltage <= 18 V", [_fact("voltage", "18", "V")])
    assert result and result["status"] == "met"


def test_range_matches_converted_value_inclusive_of_endpoints():
    result = evaluate_requirement("length between 10 and 20 cm", [_fact("length", "0.1", "m")])
    assert result and result["status"] == "met"


def test_wrong_field_or_incompatible_dimension_stays_unknown():
    fact = _fact("power", "18", "W")
    assert evaluate_requirement("voltage at least 18 V", [fact]) == {
        "status": "unknown", "evidence": "", "source": ""}
    assert evaluate_requirement("weight under 20 kg", [_fact("length", "1", "m")]) == {
        "status": "unknown", "evidence": "", "source": ""}
    assert evaluate_requirement("at least 18 V", [
        _fact("voltage", "18", "V"), _fact("voltage_alt", "20", "V")
    ]) == {"status": "unknown", "evidence": "", "source": ""}


def test_identity_codes_are_never_treated_as_measurements():
    code = _fact("model", "18", "V", identity=True)
    assert evaluate_requirement("voltage at least 18 V", [code]) == {
        "status": "unknown", "evidence": "", "source": ""}


def test_unsupported_numeric_and_negated_phrases_are_consumed_as_unknown():
    assert evaluate_requirement("at least 18 widgets", [_fact("note", "18", "widgets")]) == {
        "status": "unknown", "evidence": "", "source": ""}
    assert evaluate_requirement("not red", [_fact("colour", "red", "")]) == {
        "status": "unknown", "evidence": "", "source": ""}
    assert evaluate_requirement("at least 1,200 kg", [_fact("weight", "2", "kg")]) == {
        "status": "unknown", "evidence": "", "source": ""}


def test_compound_numeric_constraints_are_not_partially_interpreted():
    phrase = "width under 50 cm and height over 100 cm"
    facts = [_fact("width", "40", "cm"), _fact("height", "120", "cm")]
    assert evaluate_requirement(phrase, facts) == {
        "status": "unknown", "evidence": "", "source": ""}


def test_only_ordinary_positive_text_is_left_to_lexical_fallback():
    assert evaluate_requirement("red", [_fact("colour", "red", "")]) is None
