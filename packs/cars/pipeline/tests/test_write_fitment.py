"""write_variants also emits the fitment projection.

packs/cars/data/fitment/*.yaml maps variant_id -> the part codes that variant is
built from. Every one of those fields (engine_family, transmission_code,
electrical_code, body_code) is ALREADY a column on the variant row — the fitment
file is a pure projection of the variants file, not independent data.

It was nevertheless hand-maintained, so onboarding a variant wrote it into the
variants YAML and silently left fitment behind. sync_parts assembles claims via
fitment, so the new variant matched a listing and then served ZERO claims (live,
2026-07-13: the Golf 1.2 TSI). Deriving it removes the manual step CLAUDE.md's
scalability principle bans.
"""

import yaml

from packs.cars.pipeline.catalog.write_variants import build_fitment_rows


def _variant(**over):
    row = {
        "id": "golf7_ea211_110_dsg",
        "engine_family": "ea211",
        "transmission_code": "dq200",
        "electrical_code": "golf7_elec",
        "body_code": "golf7_body",
        "make": "volkswagen",
        "displacement_cc": 1197,  # not a fitment axis — must not leak through
    }
    row.update(over)
    return row


def test_fitment_row_is_projected_from_the_variant_row():
    rows = build_fitment_rows([_variant()])
    assert rows == [
        {
            "variant_id": "golf7_ea211_110_dsg",
            "engine_family": "ea211",
            "transmission_code": "dq200",
            "electrical_code": "golf7_elec",
            "body_code": "golf7_body",
        }
    ]


def test_non_fitment_columns_do_not_leak_into_fitment():
    row = build_fitment_rows([_variant()])[0]
    assert "displacement_cc" not in row
    assert "make" not in row


def test_every_variant_produces_exactly_one_fitment_row():
    rows = build_fitment_rows([_variant(id="a"), _variant(id="b")])
    assert [r["variant_id"] for r in rows] == ["a", "b"]


def test_live_catalog_fitment_covers_every_variant():
    """Regression: the shipped fitment file must not lag the variants file.

    This is the bug that made the Golf 1.2 TSI match a listing and serve nothing.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[4] / "packs" / "cars" / "data"
    for variants_path in sorted((root / "variants").glob("*.yaml")):
        fitment_path = root / "fitment" / variants_path.name
        variant_ids = {r["id"] for r in yaml.safe_load(variants_path.read_text())}
        fitted_ids = {
            r["variant_id"] for r in yaml.safe_load(fitment_path.read_text()) or []
        }
        missing = variant_ids - fitted_ids
        assert not missing, (
            f"{fitment_path.name} is missing fitment for: {sorted(missing)}"
        )
