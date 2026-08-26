"""The condition evaluator — the generic replacement for resolver.py's gates.

Today's serving path hard-codes `min_mileage_km`, `max_mileage_km`,
`min_age_years`, `applies_year_from/to`, `requires_equipment`, a maintenance
interval block, and five car-specific compatibility checks. All of them are one
mechanism: *does this claim apply, given what the reader could tell us?*

The answer has three states, not two. A claim whose gate cannot be evaluated —
because the ad did not say the mileage — must neither be hidden nor treated as
certain. It is served and downranked. That is the fail-open rule from CLAUDE.md's
automation principle, and `on_missing` is where it lives.
"""

import pytest

from kriko.lookup.conditions import Condition, Outcome, evaluate, evaluate_all


def _c(key="usage_km", op="gte", value=None, text="", on_missing="open", weight=0.7):
    return Condition(key=key, op=op, value_num=value, value_text=text,
                     on_missing=on_missing, weight=weight)


# ── numeric comparison ───────────────────────────────────────────────────

def test_gte_holds_at_and_above_the_threshold():
    cond = _c(op="gte", value=100_000)
    assert evaluate(cond, {"usage_km": 150_000}).state == "met"
    assert evaluate(cond, {"usage_km": 100_000}).state == "met"
    assert evaluate(cond, {"usage_km": 80_000}).state == "unmet"


def test_lte_holds_at_and_below_the_threshold():
    cond = _c(op="lte", value=2016)
    assert evaluate(cond, {"usage_km": 2014}).state == "met"
    assert evaluate(cond, {"usage_km": 2016}).state == "met"
    assert evaluate(cond, {"usage_km": 2018}).state == "unmet"


def test_numeric_context_tolerates_strings_and_separators():
    """Adapters scrape text; '150.000 km' must not silently become unknown."""
    cond = _c(op="gte", value=100_000)
    assert evaluate(cond, {"usage_km": "150,000"}).state == "met"
    assert evaluate(cond, {"usage_km": " 150000 "}).state == "met"


# ── equality and membership ──────────────────────────────────────────────

def test_eq_and_neq_compare_case_insensitively():
    assert evaluate(_c(key="fuel", op="eq", text="diesel"),
                    {"fuel": "Diesel"}).state == "met"
    assert evaluate(_c(key="fuel", op="neq", text="manual"),
                    {"fuel": "manual"}).state == "unmet"


def test_in_matches_any_of_a_comma_separated_list():
    cond = _c(key="fuel", op="in", text="petrol,diesel")
    assert evaluate(cond, {"fuel": "diesel"}).state == "met"
    assert evaluate(cond, {"fuel": "electric"}).state == "unmet"


def test_has_looks_inside_a_collection():
    """`requires_equipment` was a JSON array column; now it is `has`."""
    cond = _c(key="equipment", op="has", text="sunroof")
    assert evaluate(cond, {"equipment": ["sunroof", "leather"]}).state == "met"
    assert evaluate(cond, {"equipment": ["leather"]}).state == "unmet"
    assert evaluate(cond, {"equipment": "sunroof, leather"}).state == "met"


def test_mentions_searches_free_text():
    """The maintenance rule: if the ad proves the work was done, stand down."""
    cond = _c(key="free_text", op="mentions", text="timing belt")
    assert evaluate(cond, {"free_text": "New TIMING BELT fitted last year"}).state == "met"
    assert evaluate(cond, {"free_text": "one owner, full history"}).state == "unmet"


def test_interval_holds_once_the_first_service_point_is_passed():
    """A 300-hour interval is due at 300, 600, 900 — not only at 300."""
    cond = _c(key="usage_hours", op="interval", value=300)
    assert evaluate(cond, {"usage_hours": 120}).state == "unmet"
    assert evaluate(cond, {"usage_hours": 305}).state == "met"
    assert evaluate(cond, {"usage_hours": 1_250}).state == "met"


# ── the missing-value contract ───────────────────────────────────────────

def test_missing_context_defaults_to_open_and_downranks():
    """Unknown is not the same as false. Serve it, but rank it below the certain."""
    out = evaluate(_c(op="gte", value=100_000, weight=0.7), {})
    assert out.state == "unknown"
    assert out.weight == 0.7
    assert out.served is True


def test_missing_context_with_closed_hides_the_claim():
    out = evaluate(_c(op="gte", value=100_000, on_missing="closed"), {})
    assert out.state == "unknown"
    assert out.served is False


def test_missing_context_with_ignore_is_neutral():
    """For gates that only ever narrow — absence must not cost the claim rank."""
    out = evaluate(_c(op="gte", value=100_000, on_missing="ignore"), {})
    assert out.state == "unknown"
    assert out.served is True
    assert out.weight == 1.0


def test_a_met_condition_costs_no_rank():
    assert evaluate(_c(op="gte", value=100), {"usage_km": 200}).weight == 1.0


def test_an_unmet_condition_is_not_served():
    assert evaluate(_c(op="gte", value=100), {"usage_km": 10}).served is False


def test_unparseable_context_is_unknown_not_unmet():
    """A scrape that yielded 'çok temiz' must not read as low mileage."""
    out = evaluate(_c(op="gte", value=100_000), {"usage_km": "çok temiz"})
    assert out.state == "unknown"


def test_an_unknown_operator_is_a_build_error_not_a_silent_pass():
    with pytest.raises(ValueError, match="unknown operator"):
        evaluate(_c(op="approximately"), {"usage_km": 5})


# ── combining conditions ─────────────────────────────────────────────────

def test_all_conditions_must_be_served_for_the_claim_to_show():
    conds = [_c(op="gte", value=100), _c(key="fuel", op="eq", text="diesel")]
    served, weight, _ = evaluate_all(conds, {"usage_km": 200, "fuel": "petrol"})
    assert served is False


def test_weights_multiply_across_unknown_conditions():
    """Two unknowns are less certain than one, and rank accordingly."""
    conds = [_c(op="gte", value=100, weight=0.7),
             _c(key="usage_hours", op="gte", value=5, weight=0.5)]
    served, weight, outcomes = evaluate_all(conds, {})
    assert served is True
    assert weight == pytest.approx(0.35)
    assert [o.state for o in outcomes] == ["unknown", "unknown"]


def test_no_conditions_means_always_applies_at_full_weight():
    served, weight, outcomes = evaluate_all([], {})
    assert (served, weight, outcomes) == (True, 1.0, [])


def test_outcome_is_reportable_so_why_shown_can_explain_itself():
    """Every downrank must be explainable to the reader, not a silent number."""
    out = evaluate(_c(key="usage_km", op="gte", value=100_000), {})
    assert isinstance(out, Outcome)
    assert "usage_km" in out.reason


# ── list-aware text matching ─────────────────────────────────────────────

def test_mentions_takes_a_list_and_means_any_of():
    cond = _c(key="free_text", op="mentions", text="triger,timing belt,cam belt")
    assert evaluate(cond, {"free_text": "yeni TRIGER takıldı"}).state == "met"
    assert evaluate(cond, {"free_text": "full service history"}).state == "unmet"


def test_not_mentions_expresses_due_unless_the_ad_proves_otherwise():
    """The maintenance rule. Silence is the signal, so silence must serve."""
    cond = _c(key="free_text", op="not_mentions",
              text="debriyaj değiş,clutch replaced", on_missing="open")
    assert evaluate(cond, {"free_text": "tek elden, bakımlı"}).state == "met"
    assert evaluate(cond, {"free_text": "geçen ay CLUTCH REPLACED"}).state == "unmet"


def test_an_absent_description_still_serves_a_maintenance_claim():
    """No description at all must not silently retire a due service item."""
    out = evaluate(_c(key="free_text", op="not_mentions", text="clutch replaced"), {})
    assert out.served is True
