"""sync_parts() must warn about fitment references to missing or zero-claim
part files — the sync-time half of the dw5/dw6 recurrence guard (backlog B7,
CLAUDE.md generalization principle).

Before this, sync_parts() silently `continue`d past a fitment row referencing a
part_id with no file, and a zero-claim part (dw5/dw6) produced no links and no
warning — so an automatic variant could serve zero gearbox claims with nothing
flagging it. The pseudo-code `manual` deliberately has no file and must stay
silent. Warnings only: what gets synced is unchanged.
"""

import logging

import yaml

import backend.sync as sync_mod
from backend.db.models import Variant


def _setup_catalog(tmp_path, monkeypatch, *, parts, fitment):
    parts_dir = tmp_path / "parts"
    fitment_dir = tmp_path / "fitment"
    for rel, obj in parts.items():
        path = parts_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(obj, sort_keys=False))
    fitment_dir.mkdir(parents=True, exist_ok=True)
    (fitment_dir / "testmake_testmodel.yaml").write_text(yaml.dump(fitment, sort_keys=False))
    monkeypatch.setattr(sync_mod, "PARTS_DIR", parts_dir)
    monkeypatch.setattr(sync_mod, "FITMENT_DIR", fitment_dir)


def _part(part_id, part_type, claims):
    return {"part_id": part_id, "part_type": part_type, "claims": claims}


def _claim():
    return {"claim_key": "c1", "title": "t", "domain": "engine",
            "severity": "low", "status": "review",
            "rationale": "r", "inspection_advice": "a",
            "sources": [{"source_url": "https://x", "quote": "q"}]}


def _add_variant(db, vid):
    db.add(Variant(
        id=vid, make="testmake", model="testmodel", engine_code="X",
        engine_family="eng1", fuel="petrol", displacement_cc=1200,
        transmission="automatic", transmission_code="tc1",
        year_from=2020, market="TR",
    ))
    db.flush()


def test_warns_on_zero_claim_part(tmp_path, monkeypatch, db, caplog):
    _setup_catalog(
        tmp_path, monkeypatch,
        parts={
            "engine/eng1.yaml": _part("eng1", "engine", [_claim()]),
            "transmission/tc1.yaml": _part("tc1", "transmission", []),  # empty, like dw5
        },
        fitment=[{"variant_id": "tm1", "engine_family": "eng1", "transmission_code": "tc1"}],
    )
    _add_variant(db, "tm1")

    with caplog.at_level(logging.WARNING, logger="backend.sync"):
        sync_mod.sync_parts(db)

    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("tc1" in m and "0 claim" in m.lower() for m in msgs), msgs


def test_warns_on_missing_part_file(tmp_path, monkeypatch, db, caplog):
    _setup_catalog(
        tmp_path, monkeypatch,
        parts={"engine/eng1.yaml": _part("eng1", "engine", [_claim()])},
        fitment=[{"variant_id": "tm1", "engine_family": "eng1", "transmission_code": "ghost"}],
    )
    _add_variant(db, "tm1")

    with caplog.at_level(logging.WARNING, logger="backend.sync"):
        sync_mod.sync_parts(db)

    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("ghost" in m for m in msgs), msgs


def test_pseudo_manual_does_not_warn(tmp_path, monkeypatch, db, caplog):
    _setup_catalog(
        tmp_path, monkeypatch,
        parts={"engine/eng1.yaml": _part("eng1", "engine", [_claim()])},
        fitment=[{"variant_id": "tm1", "engine_family": "eng1", "transmission_code": "manual"}],
    )
    _add_variant(db, "tm1")

    with caplog.at_level(logging.WARNING, logger="backend.sync"):
        sync_mod.sync_parts(db)

    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("manual" in m for m in msgs), msgs


def test_zero_claim_warning_deduped_across_variants(tmp_path, monkeypatch, db, caplog):
    """Two variants pointing at the same empty part → one warning, not two."""
    _setup_catalog(
        tmp_path, monkeypatch,
        parts={
            "engine/eng1.yaml": _part("eng1", "engine", [_claim()]),
            "transmission/tc1.yaml": _part("tc1", "transmission", []),
        },
        fitment=[
            {"variant_id": "tm1", "engine_family": "eng1", "transmission_code": "tc1"},
            {"variant_id": "tm2", "engine_family": "eng1", "transmission_code": "tc1"},
        ],
    )
    _add_variant(db, "tm1")
    _add_variant(db, "tm2")

    with caplog.at_level(logging.WARNING, logger="backend.sync"):
        sync_mod.sync_parts(db)

    tc1_warnings = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "tc1" in r.getMessage() and "0 claim" in r.getMessage().lower()
    ]
    assert len(tc1_warnings) == 1, [r.getMessage() for r in tc1_warnings]
