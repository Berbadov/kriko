"""to_maintenance() — the pure mutation behind packs/cars/pipeline/maintenance.py.

Reclassifies an interval-shaped known_issue claim to kind=maintenance with a
maintenance interval block that _resolve_maintenance_strength (backend/core/
resolver.py) can serve as due/due_stated. Fail-safe: a matched interval-vocab
term with NO derivable interval stays known_issue — the script never emits an
invalid maintenance claim (validate_part_yaml requires a maintenance block).
"""

from packs.cars.pipeline.claims.maintenance import (
    detect_maintenance_kind,
    to_maintenance,
)


def _claim(**kw):
    base = {
        "claim_key": "c1", "title": "", "kind": "known_issue",
        "domain": "engine", "severity": "high", "status": "review",
        "rationale": "", "inspection_advice": "x",
    }
    base.update(kw)
    return base


# ── detection (closed interval vocabulary) ───────────────────────────────────

def test_detect_timing_belt_en():
    assert detect_maintenance_kind(
        "Timing belt replacement interval critical") == "timing_belt"


def test_detect_triger_turkish():
    assert detect_maintenance_kind(
        "Triger kayışı değişim aralığı") == "timing_belt"


def test_detect_dsg_fluid_but_not_bare_dsg_failure():
    assert detect_maintenance_kind("DSG fluid change interval") == "dsg_fluid"
    # A bare DSG *failure* is a known_issue, not a maintenance interval — the
    # vocab requires the fluid/oil/service qualifier, never bare "dsg".
    assert detect_maintenance_kind(
        "DQ200 mechatronics valve body cracking") is None
    assert detect_maintenance_kind(
        "DSG transmission shuddering and jerking") is None


def test_detect_clutch_wear():
    assert detect_maintenance_kind(
        "Clutch pack wear in high-torque applications") == "clutch"


def test_detect_non_maintenance_returns_none():
    assert detect_maintenance_kind(
        "Turbo wastegate corrosion and seizure") is None
    assert detect_maintenance_kind(
        "Plastic water pump housing cracking/leaking") is None


# ── to_maintenance mutation ──────────────────────────────────────────────────

def test_reclassify_uses_min_mileage_km_as_interval():
    c = _claim(
        title="Timing belt design flaw requiring mandatory replacement",
        applies_when={"min_mileage_km": 60000},
    )
    assert to_maintenance(c) is True
    assert c["kind"] == "maintenance"
    assert c["maintenance"]["interval_km"] == 60000
    assert c["maintenance"]["evidence_keywords"]  # non-empty list
    # The consumed gate is moved into interval_km; the maintenance serving path
    # ignores min_mileage_km, so leaving it would be a dead field.
    assert "min_mileage_km" not in c.get("applies_when", {})


def test_reclassify_grounds_interval_from_text_when_no_gate():
    c = _claim(
        title="Timing belt replacement interval critical",
        rationale="The belt must be replaced every 90,000 km.",
    )
    assert to_maintenance(c) is True
    assert c["maintenance"]["interval_km"] == 90000


def test_failsafe_no_interval_stays_known_issue():
    c = _claim(
        title="Timing belt wear and chirp",
        rationale="The belt is prone to premature wear and failure.",
    )
    assert to_maintenance(c) is False
    assert c["kind"] == "known_issue"
    assert "maintenance" not in c


def test_failsafe_non_vocab_stays_known_issue():
    # A gated non-maintenance claim must not be dragged in by its mileage.
    c = _claim(title="Turbo wastegate rattle",
               applies_when={"min_mileage_km": 90000})
    assert to_maintenance(c) is False
    assert c["kind"] == "known_issue"
    assert "maintenance" not in c


def test_grounds_interval_years():
    c = _claim(
        title="Timing belt service",
        rationale="Belt due at 90,000 km or every 5 years, whichever comes first.",
    )
    assert to_maintenance(c) is True
    assert c["maintenance"]["interval_km"] == 90000
    assert c["maintenance"]["interval_years"] == 5


def test_idempotent_when_already_maintenance():
    c = _claim(title="Timing belt", kind="maintenance",
               maintenance={"interval_km": 90000, "evidence_keywords": ["x"]})
    assert to_maintenance(c) is False


def test_preserves_other_applies_when_keys():
    c = _claim(
        title="Clutch wear on high-torque DSG",
        applies_when={"min_mileage_km": 80000, "applies_year_from": 2015},
    )
    assert to_maintenance(c) is True
    assert c["maintenance"]["interval_km"] == 80000
    assert c["applies_when"]["applies_year_from"] == 2015  # untouched
    assert "min_mileage_km" not in c["applies_when"]


def test_reclassified_claim_satisfies_validator_rule():
    # validate_part_yaml errors if kind==maintenance and not claim.get("maintenance").
    c = _claim(title="Timing belt replacement",
               applies_when={"min_mileage_km": 90000})
    to_maintenance(c)
    assert c["kind"] == "maintenance"
    assert c.get("maintenance")  # block present → passes the validator rule


# ── Interval plausibility (live-probe finding) ──────────────────────────────
#
# The interval was derived from a mileage figure grounded in the claim text —
# but that figure is usually a failure *onset* ("clutch squeal from 15.000 km"),
# not a service interval. That let nonsense through: a class-action lawsuit
# became a "30.000 km timing chain service", and a 20.000 km "cam belt" fired as
# DUE on a nearly-new car. A derived interval must now fall inside the category's
# plausible service window or the claim stays a known_issue.

def test_implausibly_short_clutch_interval_is_rejected():
    # A clutch is not *serviced* every 15.000 km — this is a failure onset.
    claim = _claim(title="7DCT clutch squeal",
                   rationale="Clutch squeal reported from 15.000 km onwards.")
    assert to_maintenance(claim) is False
    assert claim["kind"] == "known_issue"


def test_implausibly_short_timing_belt_interval_is_rejected():
    claim = _claim(title="1.2 PureTech timing belt",
                   rationale="Wet timing belt degrades, reported at 20.000 km.")
    assert to_maintenance(claim) is False
    assert claim["kind"] == "known_issue"


def test_timing_chain_is_never_maintenance():
    # A chain is a lifetime component: it has no service interval. "Chain stretch"
    # is a known failure, and must keep being served as one.
    claim = _claim(title="Timing chain stretch",
                   rationale="Chain stretches, typically by 90.000 km.")
    assert to_maintenance(claim) is False
    assert claim["kind"] == "known_issue"
    assert detect_maintenance_kind("timing chain stretch") is None


def test_plausible_timing_belt_interval_still_reclassifies():
    claim = _claim(title="Timing belt replacement",
                   rationale="Cam belt must be replaced every 120.000 km.")
    assert to_maintenance(claim) is True
    assert claim["kind"] == "maintenance"
    assert claim["maintenance"]["interval_km"] == 120000


def test_plausible_dsg_fluid_interval_still_reclassifies():
    claim = _claim(title="DSG fluid service",
                   rationale="DSG mechatronic fluid change due every 60.000 km.")
    assert to_maintenance(claim) is True
    assert claim["maintenance"]["interval_km"] == 60000
