"""ledger.swap — serve the ledger export instead of the legacy parts catalog (B16).

The swap is mechanical: legacy part ids remap to the export's merged identities
(k9k_110 -> k9k) via the power-collapse rule, superseded legacy files are
replaced by export files, non-superseded files are retained, and fitment axes
are rewritten. The automated acceptance gate (parity loss, coverage, serving
monotonicity) decides whether the swap may land — no human sign-off (G5).
"""

import yaml

from knowledge.ledger.export import merged_part_id
from knowledge.ledger.swap import apply, build_plan


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(obj, sort_keys=False))


def _part(pid, ptype, n_claims=2):
    claims = [{
        "claim_key": f"{pid}_c{i}", "title": f"{pid} claim {i}", "domain": ptype,
        "severity": "medium", "status": "review", "rationale": "r",
        "inspection_advice": "a", "sources": [],
    } for i in range(n_claims)]
    return {"part_id": pid, "part_type": ptype, "claims": claims}


def _fitment_row(vid, **axes):
    return {"variant_id": vid, **axes}


def _catalog(tmp_path, parts: dict[str, dict], fitment: list[dict], export: dict[str, dict]):
    """parts: {pid: part dict}; export: {pid: part dict} written to its own dir."""
    (tmp_path / "parts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "fitment").mkdir(parents=True, exist_ok=True)
    (tmp_path / "variants").mkdir(parents=True, exist_ok=True)
    for pid, d in parts.items():
        _write(tmp_path / "parts" / d["part_type"] / f"{pid}.yaml", d)
    _write(tmp_path / "fitment" / "t.yaml", fitment)
    (tmp_path / "variants" / "t.yaml").write_text(yaml.dump([
        {"id": "t1", "make": "t", "model": "m", "generation": "I",
         "engine_code": "E1", "engine_family": "eng1", "fuel": "petrol",
         "displacement_cc": 1200, "power_min_hp": 100, "power_max_hp": 100,
         "transmission": "manual", "transmission_code": "manual",
         "electrical_code": "elec1", "body_code": "body1",
         "year_from": 2020, "market": "TR", "notes": "n"},
    ], sort_keys=False))
    exp = tmp_path / "export"
    exp.mkdir(parents=True, exist_ok=True)
    for pid, d in export.items():
        _write(exp / f"{pid}.yaml", d)
    return tmp_path


def test_merged_part_id_power_collapse():
    assert merged_part_id("k9k_110") == "k9k"
    assert merged_part_id("h5f_130") == "h5f"
    assert merged_part_id("dc4") == "dc4"
    assert merged_part_id("ea288") == "ea288"


def test_plan_supersedes_and_remaps(tmp_path):
    root = _catalog(
        tmp_path,
        parts={
            "k9k_85": _part("k9k_85", "engine"),
            "k9k_110": _part("k9k_110", "engine"),
            "dc4": _part("dc4", "transmission"),
            "dw5": _part("dw5", "transmission"),
        },
        fitment=[_fitment_row("t1", engine_family="k9k_110", transmission_code="dc4")],
        export={"k9k": _part("k9k", "engine"), "dc4": _part("dc4", "transmission")},
    )
    plan = build_plan(root / "export", root)
    assert plan.remap == {"k9k_110": "k9k", "k9k_85": "k9k"}
    assert sorted(plan.superseded) == ["dc4", "k9k_110", "k9k_85"]
    assert plan.retained == ["dw5"]
    assert plan.fitment_edits == 1
    assert plan.missing_after == []


def test_plan_pseudo_manual_never_a_gap(tmp_path):
    root = _catalog(
        tmp_path,
        parts={"k9k_110": _part("k9k_110", "engine")},
        fitment=[_fitment_row("t1", engine_family="k9k_110", transmission_code="manual")],
        export={"k9k": _part("k9k", "engine")},
    )
    plan = build_plan(root / "export", root)
    assert plan.missing_after == []


def test_plan_flags_export_gap(tmp_path):
    root = _catalog(
        tmp_path,
        parts={"k9k_110": _part("k9k_110", "engine")},
        fitment=[_fitment_row("t1", engine_family="k9k_110"),
                 _fitment_row("t2", engine_family="ghost")],
        export={},  # k9k never exported
    )
    plan = build_plan(root / "export", root)
    assert plan.retained == ["k9k_110"]      # not superseded — export lacks it
    assert plan.remap == {}                  # no remap without an export target
    assert plan.missing_after == ["ghost"]   # fits neither legacy nor export


def test_apply_writes_remaps_deletes_and_retains(tmp_path):
    root = _catalog(
        tmp_path,
        parts={
            "k9k_110": _part("k9k_110", "engine"),
            "dc4": _part("dc4", "transmission", n_claims=1),
            "dw5": _part("dw5", "transmission"),
        },
        fitment=[_fitment_row("t1", engine_family="k9k_110", transmission_code="dc4",
                              electrical_code="elec1", body_code="body1")],
        export={"k9k": _part("k9k", "engine", n_claims=3),
                "dc4": _part("dc4", "transmission", n_claims=2)},
    )
    plan = build_plan(root / "export", root)
    apply(root / "export", root, plan)

    k9k = yaml.safe_load((root / "parts" / "engine" / "k9k.yaml").read_text())
    assert len(k9k["claims"]) == 3            # export file written
    assert not (root / "parts" / "engine" / "k9k_110.yaml").exists()  # legacy deleted
    dc4 = yaml.safe_load((root / "parts" / "transmission" / "dc4.yaml").read_text())
    assert len(dc4["claims"]) == 2            # non-split superseded: overwritten, not deleted
    assert (root / "parts" / "transmission" / "dw5.yaml").exists()    # retained
    fit = yaml.safe_load((root / "fitment" / "t.yaml").read_text())
    assert fit[0]["engine_family"] == "k9k"   # remapped
    assert fit[0]["transmission_code"] == "dc4"
    assert fit[0]["electrical_code"] == "elec1"  # non-part columns untouched


def test_apply_non_split_export_files_survive(tmp_path):
    """Regression: the delete pass used to rglob the legacy name, which also
    deleted the freshly-written export file for non-split ids (dc4, ea288…)."""
    root = _catalog(
        tmp_path,
        parts={"ea288": _part("ea288", "engine", n_claims=9)},
        fitment=[_fitment_row("t1", engine_family="ea288")],
        export={"ea288": _part("ea288", "engine", n_claims=4)},
    )
    plan = build_plan(root / "export", root)
    apply(root / "export", root, plan)
    out = yaml.safe_load((root / "parts" / "engine" / "ea288.yaml").read_text())
    assert len(out["claims"]) == 4
