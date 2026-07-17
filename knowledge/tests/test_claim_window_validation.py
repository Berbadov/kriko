"""validate_part() model-year-window checks (Phase 1).

A claim may carry an optional applies_when.applies_year_from/applies_year_to
model-year window. When present, both bounds must be integers (or absent) and
from <= to. This runs at the one-way sync gate so a malformed window fails
before it can ever serve.
"""

from pathlib import Path

import yaml

from knowledge.parts.validate_part_yaml import validate_part


def _write_part(tmp_path: Path, applies_when) -> Path:
    """Write a minimal, otherwise-valid body part with one claim carrying the
    given applies_when block (or none if applies_when is None)."""
    claim = {
        "claim_key": "test_window_claim",
        "title": "Test window claim",
        "kind": "known_issue",
        "domain": "engine",
        "severity": "medium",
        "status": "held",  # not verified/review → no sources required
        "rationale": "Test rationale.",
        "inspection_advice": "Test advice.",
    }
    if applies_when is not None:
        claim["applies_when"] = applies_when
    data = {
        "part_id": "testwindow",
        "part_type": "body",  # not engine/transmission → no code_family required
        "display_name": "Test Window Part",
        "manufacturer": "renault",
        "claims": [claim],
    }
    path = tmp_path / "testwindow.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
    return path


def _window_errors(errors: list[str]) -> list[str]:
    return [e for e in errors if "applies_year" in e]


def test_valid_year_window_passes(tmp_path):
    path = _write_part(tmp_path, {"applies_year_from": 2019, "applies_year_to": 2022})
    assert _window_errors(validate_part(path)) == []


def test_open_ended_window_passes(tmp_path):
    path = _write_part(tmp_path, {"applies_year_from": 2023})
    assert _window_errors(validate_part(path)) == []


def test_absent_applies_when_passes(tmp_path):
    path = _write_part(tmp_path, None)
    assert _window_errors(validate_part(path)) == []


def test_non_int_year_bound_errors(tmp_path):
    path = _write_part(tmp_path, {"applies_year_from": "2019"})
    assert _window_errors(validate_part(path)), "expected an error for a non-int year bound"


def test_from_greater_than_to_errors(tmp_path):
    path = _write_part(tmp_path, {"applies_year_from": 2022, "applies_year_to": 2019})
    assert _window_errors(validate_part(path)), "expected an error for from > to"
