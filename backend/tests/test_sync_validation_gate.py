"""sync.py refuses to push invalid/contaminated part YAML into the servable
DB. This is the enforcement point for docs/design_flaws.md Flaw 1: a
hand-edited file or a pipeline run that skips promote.py's gates would
otherwise reach buyers the instant someone runs `python -m backend.sync` —
validate_part_yaml.py existing isn't enough if nothing calls it.
"""

import pytest

import backend.sync as sync_mod

_BAD_PART_YAML = """
part_id: dq381
part_type: transmission
display_name: Volkswagen DQ381 Transmission
manufacturer: volkswagen
claims:
- claim_key: dq381_bad
  title: DQ200 dry-clutch pressure circuit failure
  kind: known_issue
  domain: transmission
  severity: high
  status: review
  rationale: The DQ200 dry-clutch DSG suffers from chronic hydraulic pressure issues.
  inspection_advice: Check for hesitation.
  sources:
  - source_url: https://x
    quote: q
"""

_GOOD_PART_YAML = """
part_id: dq381
part_type: transmission
display_name: Volkswagen DQ381 Transmission
manufacturer: volkswagen
claims:
- claim_key: dq381_good
  title: DQ381 wet-clutch pack wear
  kind: known_issue
  domain: transmission
  severity: high
  status: review
  rationale: DQ381 wet dual-clutch pack wears prematurely under heavy load.
  inspection_advice: Check for shudder on takeoff.
  sources:
  - source_url: https://x
    quote: q
"""


def test_refuses_on_sibling_contaminated_part_yaml(tmp_path, monkeypatch):
    bad_dir = tmp_path / "parts" / "transmission"
    bad_dir.mkdir(parents=True)
    (bad_dir / "dq381.yaml").write_text(_BAD_PART_YAML)
    monkeypatch.setattr(sync_mod, "PARTS_DIR", tmp_path / "parts")

    with pytest.raises(SystemExit):
        sync_mod._validate_part_yaml_or_raise()


def test_passes_on_clean_part_yaml(tmp_path, monkeypatch):
    good_dir = tmp_path / "parts" / "transmission"
    good_dir.mkdir(parents=True)
    (good_dir / "dq381.yaml").write_text(_GOOD_PART_YAML)
    monkeypatch.setattr(sync_mod, "PARTS_DIR", tmp_path / "parts")

    sync_mod._validate_part_yaml_or_raise()  # must not raise
