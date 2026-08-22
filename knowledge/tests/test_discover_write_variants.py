"""write_variants_yaml() — scaffolds a draft variants YAML from discovered
engine/transmission specs (docs/USAGE.md onboarding Step 1), without inventing
power/year figures Wikipedia doesn't reliably give.
"""

import yaml

import knowledge.catalog.discover as discover_mod
from knowledge.catalog.discover import ModelCatalog, PartSpec, write_variants_yaml


def _catalog() -> ModelCatalog:
    return ModelCatalog(
        make="testmake",
        model="testmodel_2",
        engines=[
            PartSpec("X1", "x1", "petrol", 1200, ["manual", "edc"], ""),
            PartSpec("Y2", "y2", "diesel", 1500, ["manual", "edc"], ""),
        ],
        transmissions=["manual", "edc"],
        source="wikitext",
    )


def test_write_variants_yaml_scaffolds_draft_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(discover_mod, "VARIANTS_DIR", tmp_path)

    rows = write_variants_yaml("testmake", "testmodel_2", _catalog())

    assert len(rows) == 4  # 2 engines x 2 transmissions
    assert all(r["draft"] is True for r in rows)
    assert all("power_min_hp" not in r for r in rows)
    assert {r["engine_family"] for r in rows} == {"x1", "y2"}
    assert {r["transmission_code"] for r in rows} == {"manual", "edc"}
    # generation suffix stripped from "testmodel_2" into base model + generation field
    assert all(r["model"] == "testmodel" for r in rows)
    assert all(r["generation"] == "2" for r in rows)

    written = yaml.safe_load((tmp_path / "testmake_testmodel_2.yaml").read_text())
    assert written == rows


def test_write_variants_yaml_never_overwrites_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(discover_mod, "VARIANTS_DIR", tmp_path)
    path = tmp_path / "testmake_testmodel_2.yaml"
    path.write_text(yaml.dump([{"id": "hand-curated", "power_min_hp": 100}]))

    rows = write_variants_yaml("testmake", "testmodel_2", _catalog())

    assert rows == []
    assert yaml.safe_load(path.read_text()) == [{"id": "hand-curated", "power_min_hp": 100}]


def test_write_variants_yaml_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(discover_mod, "VARIANTS_DIR", tmp_path)

    rows = write_variants_yaml("testmake", "testmodel_2", _catalog(), dry_run=True)

    assert len(rows) == 4
    assert not (tmp_path / "testmake_testmodel_2.yaml").exists()


# ── shared_codes: derived, not hand-enumerated ───────────────────────────────
#
# Replaced _SHARED_CODES, a hand-written dict that listed clio_5 and golf_7 and
# had already gone stale for megane_4 — whose part files exist and whose variant
# rows carry the codes, but which the dict never learned about.

def test_shared_codes_reproduces_the_hand_written_entries():
    from knowledge.catalog.write_variants import shared_codes
    assert shared_codes("renault_clio_5") == {
        "electrical_code": "clio5_elec", "body_code": "clio5_body"}
    assert shared_codes("volkswagen_golf_7") == {
        "electrical_code": "golf7_elec", "body_code": "golf7_body"}


def test_shared_codes_covers_the_model_the_dict_had_gone_stale_for():
    """megane_4 has megane4_elec.yaml and megane4_body.yaml but was never listed.

    Regenerating it would have dropped both axes from every row.
    """
    from knowledge.catalog.write_variants import shared_codes
    assert shared_codes("renault_megane_4") == {
        "electrical_code": "megane4_elec", "body_code": "megane4_body"}


def test_shared_codes_fails_open_for_a_model_with_no_part_files():
    """No guessed codes — an absent part file means no axis (automation principle)."""
    from knowledge.catalog.write_variants import shared_codes
    assert shared_codes("mazda_cx_5") == {}


def test_onboarding_a_model_needs_no_python_edit_for_shared_codes():
    import knowledge.catalog.write_variants as wv
    assert not hasattr(wv, "_SHARED_CODES")
