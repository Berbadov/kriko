"""packs.cars.coverage — cars-pack catalog coverage report over YAML only (no DB, no
network). This is the recurrence guard for the dw5/dw6 class of bug (backlog
B7, CLAUDE.md generalization principle): a fitment row can point at a part_id
with no file, a part file can carry zero (or zero *servable*) claims, a part
can sit in the catalog wired to no variant, or an automatic-transmission
variant can reference no real transmission part — and nothing today surfaces
any of it.

Finding kinds (verbatim from the brief):
  missing_part            — fitment row's part_id has no part YAML file
  zero_claim_part         — part YAML has 0 claims, or claims but none servable
  orphan_part             — part YAML that no fitment row references
  auto_variant_no_tx_part — automatic-tech variant referencing no tx part
  variant_no_emissions    — diesel variant with no emissions value (B11)

The pseudo-code "manual" is never flagged as missing/orphan — manual gearboxes
deliberately have no part file.

Everything here is catalog-derived: axis names (engine/transmission/electrical/
body/...) come from the *_family / *_code field-naming convention already used
by the fitment rows themselves, so a new axis or a new car needs no code
change here.

`SERVABLE_STATUSES` is no longer a Python constant: the pack manifest's
`[status_confidence]` table is the authority, and `servable_statuses()` reads
it. The test below therefore asserts against what the *builder* would export.
"""

import yaml

from packs.cars import coverage

SERVABLE_STATUSES = coverage.servable_statuses()


# ── fixture helpers ──────────────────────────────────────────────────────────


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(obj, sort_keys=False))


def _variant(vid, **over):
    row = dict(
        id=vid, make="testmake", model="testmodel", engine_code="X",
        engine_family="eng1", fuel="petrol", displacement_cc=1200,
        power_min_hp=100, power_max_hp=100, transmission="manual",
        transmission_code="manual", electrical_code="elec1", body_code="body1",
        year_from=2020, market="TR",
    )
    row.update(over)
    return row


def _part(part_id, part_type, claims):
    return {"part_id": part_id, "part_type": part_type, "claims": claims}


def _claim(status="verified"):
    return {"claim_key": f"c_{status}", "title": "t", "domain": "engine",
            "severity": "low", "status": status,
            "rationale": "r", "inspection_advice": "a", "sources": []}


def _dirs(tmp_path):
    return tmp_path / "variants", tmp_path / "fitment", tmp_path / "parts"


def _clean_catalog(tmp_path):
    """A fully-covered single-model catalog: every part referenced, every
    referenced non-pseudo part file has >=1 servable claim, every part is
    referenced by some fitment row, and the one automatic variant has a real
    transmission part."""
    v, f, p = _dirs(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual"),
        _variant("tm_eng1_auto", transmission="automatic", transmission_code="tc1"),
    ])
    _write(f / "testmake_testmodel.yaml", [
        {"variant_id": "tm_eng1", "engine_family": "eng1",
         "transmission_code": "manual", "electrical_code": "elec1", "body_code": "body1"},
        {"variant_id": "tm_eng1_auto", "engine_family": "eng1",
         "transmission_code": "tc1", "electrical_code": "elec1", "body_code": "body1"},
    ])
    _write(p / "engine" / "eng1.yaml", _part("eng1", "engine", [_claim("verified")]))
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", [_claim("review")]))
    _write(p / "electrical" / "elec1.yaml", _part("elec1", "electrical", [_claim("held")]))
    _write(p / "body" / "body1.yaml", _part("body1", "body", [_claim("verified")]))
    return v, f, p


# ── clean case ───────────────────────────────────────────────────────────────


def test_clean_catalog_has_no_findings(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    assert report.findings == []
    assert not report.has_findings()


# ── missing_part ─────────────────────────────────────────────────────────────


def test_missing_part_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(f / "testmake_testmodel.yaml", [
        {"variant_id": "tm_eng1", "engine_family": "eng1",
         "transmission_code": "manual", "electrical_code": "elec1", "body_code": "body1"},
        {"variant_id": "tm_eng1_auto", "engine_family": "eng1",
         "transmission_code": "ghost", "electrical_code": "elec1", "body_code": "body1"},
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("missing_part", "ghost") in kinds


def test_pseudo_manual_never_flagged_missing(tmp_path):
    """`manual` deliberately has no part file — must never be flagged."""
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    subjects = {fl.subject for fl in report.findings}
    assert "manual" not in subjects


# ── zero_claim_part ──────────────────────────────────────────────────────────


def test_zero_claim_part_empty_list(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # tc1 file exists but has no claims at all — the dw5/dw6 case exactly.
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("zero_claim_part", "tc1") in kinds


def test_zero_claim_part_none_servable(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # tc1 has claims, but every one is in a non-servable status.
    assert set(SERVABLE_STATUSES) == {"verified", "review", "held"}
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", [
        _claim("draft"), _claim("rejected"),
    ]))
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("zero_claim_part", "tc1") in kinds


def test_servable_claim_part_not_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    subjects = {fl.subject for fl in report.findings if fl.kind == "zero_claim_part"}
    assert "tc1" not in subjects
    assert "eng1" not in subjects


# ── orphan_part ──────────────────────────────────────────────────────────────


def test_orphan_part_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    # A part file with claims that no fitment row references.
    _write(p / "transmission" / "unused.yaml", _part("unused", "transmission", [_claim()]))
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("orphan_part", "unused") in kinds


def test_referenced_part_not_flagged_orphan(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    orphans = {fl.subject for fl in report.findings if fl.kind == "orphan_part"}
    assert orphans == set()


# ── auto_variant_no_tx_part ──────────────────────────────────────────────────


def test_auto_variant_missing_tx_code_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual"),
        _variant("tm_eng1_auto", transmission="automatic", transmission_code=""),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("auto_variant_no_tx_part", "tm_eng1_auto") in kinds


def test_auto_variant_unresolvable_tx_code_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual"),
        _variant("tm_eng1_auto", transmission="automatic", transmission_code="nope"),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("auto_variant_no_tx_part", "tm_eng1_auto") in kinds


def test_auto_variant_wrong_type_part_flagged(tmp_path):
    """transmission_code resolves to a real file, but that file is not a
    transmission-type part — still "references no transmission-type part"."""
    v, f, p = _clean_catalog(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual"),
        _variant("tm_eng1_auto", transmission="automatic", transmission_code="elec1"),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("auto_variant_no_tx_part", "tm_eng1_auto") in kinds


def test_manual_variant_never_flagged_auto(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    subjects = {fl.subject for fl in report.findings if fl.kind == "auto_variant_no_tx_part"}
    assert "tm_eng1" not in subjects


def test_auto_variant_with_real_tx_part_not_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    subjects = {fl.subject for fl in report.findings if fl.kind == "auto_variant_no_tx_part"}
    assert "tm_eng1_auto" not in subjects


# ── --strict exit code / CLI ─────────────────────────────────────────────────


def test_strict_exit_zero_on_clean(tmp_path, capsys):
    _clean_catalog(tmp_path)
    code = coverage.main(["--data-dir", str(tmp_path), "--strict"])
    assert code == 0


def test_strict_exit_one_on_finding(tmp_path, capsys):
    v, f, p = _clean_catalog(tmp_path)
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    code = coverage.main(["--data-dir", str(tmp_path), "--strict"])
    assert code == 1


def test_non_strict_exit_zero_even_with_finding(tmp_path, capsys):
    v, f, p = _clean_catalog(tmp_path)
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    code = coverage.main(["--data-dir", str(tmp_path)])
    assert code == 0


def test_report_prints_grouped_by_kind(tmp_path, capsys):
    v, f, p = _clean_catalog(tmp_path)
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    coverage.main(["--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert "zero_claim_part" in out
    assert "tc1" in out


# ── variant_no_emissions (B11) ───────────────────────────────────────────────


def test_diesel_without_emissions_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual",
                 fuel="diesel"),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("variant_no_emissions", "tm_eng1") in kinds


def test_diesel_with_emissions_not_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual",
                 fuel="diesel", emissions="euro6d_temp"),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("variant_no_emissions", "tm_eng1") not in kinds


def test_petrol_variant_never_flagged_for_emissions(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    kinds = {fl.kind for fl in report.findings}
    assert "variant_no_emissions" not in kinds


# ── draft_variant (G5) ───────────────────────────────────────────────────────


def test_draft_variant_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(v / "testmake_testmodel.yaml", [
        _variant("tm_eng1", transmission="manual", transmission_code="manual"),
        _variant("tm_scaffold", transmission="automatic", transmission_code="tc1",
                 draft=True),
    ])
    report = coverage.build_report(v, f, p)
    kinds = {(fl.kind, fl.subject) for fl in report.findings}
    assert ("draft_variant", "tm_scaffold") in kinds


def test_non_draft_variant_never_flagged(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    report = coverage.build_report(v, f, p)
    subjects = {fl.subject for fl in report.findings if fl.kind == "draft_variant"}
    assert subjects == set()


# ── finding part_id/axis metadata (B19 remediation input) ────────────────────


def test_zero_claim_finding_carries_part_id_and_axis(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(p / "transmission" / "tc1.yaml", _part("tc1", "transmission", []))
    report = coverage.build_report(v, f, p)
    zero = [fl for fl in report.findings if fl.kind == "zero_claim_part"]
    assert zero and zero[0].part_id == "tc1" and zero[0].axis == "transmission"


def test_missing_part_finding_carries_part_id_and_axis(tmp_path):
    v, f, p = _clean_catalog(tmp_path)
    _write(f / "testmake_testmodel.yaml", [
        {"variant_id": "tm_eng1", "engine_family": "eng1",
         "transmission_code": "ghost", "electrical_code": "elec1", "body_code": "body1"},
    ])
    report = coverage.build_report(v, f, p)
    missing = [fl for fl in report.findings if fl.kind == "missing_part"]
    assert missing
    assert missing[0].part_id == "ghost" and missing[0].axis == "transmission"
