"""backend.tools.coverage — catalog coverage report over YAML (no DB).

This is the recurrence guard for the dw5/dw6 class of bug (CLAUDE.md
generalization principle): a variant pointing at a zero-claim or file-less
part serves nothing, and nothing warned. The tool reads variants/fitment/parts
YAML directly and flags four coverage holes:

  (a) fitment references a part_id with no part file        (skip pseudo "manual")
  (b) part file exists but has 0 claims                     (skip pseudo "manual")
  (c) variant defined in variants YAML but absent from fitment
  (d) fitment row referencing an unknown variant_id

Counting is derived from the catalog, never a hand-maintained list of makes/
codes — a new part/axis is covered the moment its YAML exists.
"""

import yaml

from backend.core.resolver import SERVABLE_STATUSES
from backend.tools import coverage


# ── fixture helpers ──────────────────────────────────────────────────────────


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(obj, sort_keys=False))


def _variant(vid, **over):
    row = dict(
        id=vid, make="testmake", model="testmodel", engine_code="X",
        engine_family="eng1", fuel="petrol", displacement_cc=1200,
        power_min_hp=100, power_max_hp=100, transmission="manual",
        transmission_code="manual", year_from=2020, market="TR",
    )
    row.update(over)
    return row


def _part(part_id, part_type, claims):
    return {"part_id": part_id, "part_type": part_type, "claims": claims}


def _claim(status):
    return {"claim_key": f"c_{status}", "title": "t", "domain": "engine",
            "severity": "low", "status": status,
            "rationale": "r", "inspection_advice": "a", "sources": []}


def _dirs(tmp_path):
    return tmp_path / "variants", tmp_path / "fitment", tmp_path / "parts"


def _clean_catalog(tmp_path):
    """A fully-covered single-model catalog: every variant in fitment, every
    referenced non-pseudo part has a file with >=1 claim."""
    v, f, p = _dirs(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", engine_family="eng1", transmission_code="manual"),
        _variant("tm_eng1_auto", engine_family="eng1", transmission_code="tc1"),
    ])
    _write(f / "testmake_testmodel.yaml", [
        {"variant_id": "tm_eng1", "engine_family": "eng1",
         "transmission_code": "manual", "electrical_code": "elec1"},
        {"variant_id": "tm_eng1_auto", "engine_family": "eng1",
         "transmission_code": "tc1", "electrical_code": "elec1"},
    ])
    _write(p / "engine" / "eng1.yaml", _part("eng1", "engine", [_claim("verified")]))
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", [_claim("review")]))
    _write(p / "electrical" / "elec1.yaml", _part("elec1", "electrical", [_claim("held")]))
    return v, f, p


# ── clean case ───────────────────────────────────────────────────────────────


def test_clean_catalog_has_no_flags(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    assert report.flags == []
    assert not report.has_flags()


# ── flag (a): missing part file ──────────────────────────────────────────────


def test_flag_missing_part_file(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # Point a variant's transmission at a code that has no part file.
    _write(f / "testmake_testmodel.yaml", [
        {"variant_id": "tm_eng1", "engine_family": "eng1", "transmission_code": "ghost"},
        {"variant_id": "tm_eng1_auto", "engine_family": "eng1", "transmission_code": "tc1"},
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.flags}
    assert ("missing_part_file", "ghost") in kinds
    assert report.has_flags()


def test_pseudo_manual_missing_file_is_not_flagged(tmp_path):
    """`manual` deliberately has no part file — must never flag (a)/(b)."""
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    subjects = {fl.subject for fl in report.flags}
    assert "manual" not in subjects


# ── flag (b): part file exists but 0 claims ──────────────────────────────────


def test_flag_zero_claim_part(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # tc1 file exists but has no claims — the dw5/dw6 case exactly.
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.flags}
    assert ("zero_claim_part", "tc1") in kinds


# ── flag (c): variant defined but absent from fitment ────────────────────────


def test_flag_variant_missing_from_fitment(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # Add a third variant to variants YAML but not to fitment.
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", engine_family="eng1", transmission_code="manual"),
        _variant("tm_eng1_auto", engine_family="eng1", transmission_code="tc1"),
        _variant("tm_orphan", engine_family="eng1", transmission_code="tc1"),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.flags}
    assert ("variant_not_in_fitment", "tm_orphan") in kinds


# ── flag (d): fitment references unknown variant ─────────────────────────────


def test_flag_unknown_variant_in_fitment(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(f / "testmake_testmodel.yaml", [
        {"variant_id": "tm_eng1", "engine_family": "eng1", "transmission_code": "manual"},
        {"variant_id": "tm_eng1_auto", "engine_family": "eng1", "transmission_code": "tc1"},
        {"variant_id": "tm_ghost_variant", "engine_family": "eng1", "transmission_code": "tc1"},
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.flags}
    assert ("unknown_variant_in_fitment", "tm_ghost_variant") in kinds


# ── servable-vs-total counting respects SERVABLE_STATUSES ────────────────────


def test_servable_vs_total_counting(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # eng1 gets a mix of statuses: verified/review/held are servable; draft &
    # rejected are not. total=5, servable=3.
    assert set(SERVABLE_STATUSES) == {"verified", "review", "held"}
    _write(p / "engine" / "eng1.yaml", _part("eng1", "engine", [
        _claim("verified"), _claim("review"), _claim("held"),
        _claim("draft"), _claim("rejected"),
    ]))
    report = coverage.build_report(v, f, p)
    row = next(r for m in report.models for r in m.rows if r.part_id == "eng1")
    assert row.total_claims == 5
    assert row.servable_claims == 3


# ── --strict exit code ───────────────────────────────────────────────────────


def test_strict_exit_zero_on_clean(tmp_path, capsys):
    _clean_catalog(tmp_path)
    code = coverage.main(["--data-dir", str(tmp_path), "--strict"])
    assert code == 0


def test_strict_exit_one_on_flag(tmp_path, capsys):
    v, f, p = _clean_catalog(tmp_path)
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    code = coverage.main(["--data-dir", str(tmp_path), "--strict"])
    assert code == 1


def test_non_strict_exit_zero_even_with_flag(tmp_path, capsys):
    v, f, p = _clean_catalog(tmp_path)
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    code = coverage.main(["--data-dir", str(tmp_path)])
    assert code == 0
