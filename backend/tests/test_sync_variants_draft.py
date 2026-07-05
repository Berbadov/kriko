"""sync_variants() must refuse draft variant rows, not silently no-op them.

knowledge.catalog.discover.write_variants_yaml() scaffolds draft rows (engine/
transmission/fuel only — no verified power/year figures, see its docstring for
why inventing those would be fabricated car data). Variant has no `draft`
column, so without an explicit skip, setattr(obj, "draft", True) would just be
silently swallowed as an unmapped instance attribute and the incomplete row
would sync anyway — this test guards against that.
"""

import yaml

import backend.sync as sync_mod
from backend.db.models import Variant

_DRAFT_ROW = [{
    "id": "testmodel_x1",
    "make": "testmake",
    "model": "testmodel",
    "engine_code": "X1",
    "engine_family": "x1",
    "fuel": "petrol",
    "displacement_cc": 1200,
    "transmission": "manual",
    "transmission_code": "manual",
    "draft": True,
}]

_FINISHED_ROW = [{
    "id": "testmodel_x1",
    "make": "testmake",
    "model": "testmodel",
    "engine_code": "X1",
    "engine_family": "x1",
    "fuel": "petrol",
    "displacement_cc": 1200,
    "power_min_hp": 100,
    "power_max_hp": 100,
    "transmission": "manual",
    "transmission_code": "manual",
    "year_from": 2020,
}]


def test_sync_variants_skips_draft_rows(tmp_path, monkeypatch, db):
    variants_dir = tmp_path / "variants"
    variants_dir.mkdir()
    (variants_dir / "testmake_testmodel.yaml").write_text(yaml.dump(_DRAFT_ROW))
    monkeypatch.setattr(sync_mod, "DATA_DIR", tmp_path)

    count = sync_mod.sync_variants(db)

    assert count == 0
    assert db.get(Variant, "testmodel_x1") is None


def test_sync_variants_syncs_finished_rows(tmp_path, monkeypatch, db):
    variants_dir = tmp_path / "variants"
    variants_dir.mkdir()
    (variants_dir / "testmake_testmodel.yaml").write_text(yaml.dump(_FINISHED_ROW))
    monkeypatch.setattr(sync_mod, "DATA_DIR", tmp_path)

    count = sync_mod.sync_variants(db)

    assert count == 1
    assert db.get(Variant, "testmodel_x1") is not None
