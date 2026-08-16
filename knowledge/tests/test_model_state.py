"""model_state — one definition of "what state is this car in".

Both the MCP `onboard_model` tool (the agent's work list) and the hub's Models
tab read this. Two copies would drift, and the agent and the human watching it
would disagree about what still needs research.

A part is `missing` (no YAML at all), `zero_claim` (stub, nothing researched
yet) or `has_claims`. A variant row is `draft` when a figure could not be
sourced — visible, never guessed.
"""

import pytest
import yaml

from knowledge.catalog import model_state

PART_STUB = "part_id: k9k\npart_type: engine\nclaims: []\n"
PART_WITH_CLAIMS = """part_id: dc4
part_type: transmission
claims:
  - id: dc4_x_v1
    title: EDC clutch judder
"""


@pytest.fixture
def data(tmp_path):
    for sub in ("variants", "fitment", "parts/engine", "parts/transmission"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "parts" / "engine" / "k9k.yaml").write_text(PART_STUB)
    (tmp_path / "parts" / "transmission" / "dc4.yaml").write_text(PART_WITH_CLAIMS)
    return tmp_path


def _write_variants(data, rows):
    (data / "variants" / "renault_megane_4.yaml").write_text(yaml.dump(rows))


def test_missing_scaffold_reports_no_variants(data):
    st = model_state.model_state("renault", "megane_4", data)
    assert st["has_variants"] is False
    assert st["has_fitment"] is False
    assert st["variants"] == 0
    assert st["parts"] == []


def test_part_with_no_yaml_is_missing(data):
    _write_variants(data, [{"id": "a", "engine_family": "nope"}])
    st = model_state.model_state("renault", "megane_4", data)
    assert st["parts"][0] == {"part_id": "nope", "part_type": "", "claims": 0,
                              "state": "missing", "axes": ["engine_family"]}


def test_part_stub_without_claims_is_zero_claim(data):
    _write_variants(data, [{"id": "a", "engine_family": "k9k"}])
    st = model_state.model_state("renault", "megane_4", data)
    assert st["parts"][0]["state"] == "zero_claim"
    assert st["parts"][0]["part_type"] == "engine"


def test_researched_part_is_has_claims_with_a_count(data):
    _write_variants(data, [{"id": "a", "transmission_code": "dc4"}])
    st = model_state.model_state("renault", "megane_4", data)
    assert st["parts"][0]["state"] == "has_claims"
    assert st["parts"][0]["claims"] == 1


def test_pseudo_codes_are_not_research_targets(data):
    """'manual' is engineering vocabulary, not a part anyone can research."""
    _write_variants(data, [{"id": "a", "transmission_code": "manual",
                            "engine_family": "k9k"}])
    st = model_state.model_state("renault", "megane_4", data)
    assert [p["part_id"] for p in st["parts"]] == ["k9k"]


def test_one_part_shared_by_two_variants_is_listed_once(data):
    _write_variants(data, [{"id": "a", "engine_family": "k9k"},
                           {"id": "b", "engine_family": "k9k"}])
    st = model_state.model_state("renault", "megane_4", data)
    assert len(st["parts"]) == 1


def test_draft_rows_report_which_figures_are_missing(data):
    _write_variants(data, [
        {"id": "sourced", "engine_family": "k9k", "displacement_cc": 1461,
         "power_min_hp": 110, "power_max_hp": 110},
        {"id": "unsourced", "engine_family": "k9k", "draft": True,
         "displacement_cc": None, "power_min_hp": None, "power_max_hp": None},
    ])
    st = model_state.model_state("renault", "megane_4", data)
    assert st["variants_draft"] == 1
    draft = st["drafts"][0]
    assert draft["id"] == "unsourced"
    assert set(draft["missing"]) == {"displacement_cc", "power_min_hp",
                                     "power_max_hp"}


def test_rollup_counts_parts_by_state(data):
    _write_variants(data, [{"id": "a", "engine_family": "k9k",
                            "transmission_code": "dc4",
                            "electrical_code": "nope"}])
    st = model_state.model_state("renault", "megane_4", data)
    assert st["rollup"] == {"missing": 1, "zero_claim": 1, "has_claims": 1}


# ── list_models ───────────────────────────────────────────────────────────────


def test_list_models_is_empty_without_catalog(data):
    assert model_state.list_models(data) == []


def test_list_models_summarizes_each_catalogued_model(data):
    _write_variants(data, [{"id": "a", "engine_family": "k9k"},
                           {"id": "b", "engine_family": "k9k", "draft": True}])
    (data / "variants" / "volkswagen_golf_7.yaml").write_text(
        yaml.dump([{"id": "g", "engine_family": "nope"}]))
    models = model_state.list_models(data)
    assert [m["model_key"] for m in models] == ["renault_megane_4",
                                                "volkswagen_golf_7"]
    meg = models[0]
    assert meg["make"] == "renault" and meg["model"] == "megane_4"
    assert meg["variants"] == 2 and meg["variants_draft"] == 1
    assert meg["rollup"]["zero_claim"] == 1


def test_list_models_ignores_a_malformed_file(data):
    (data / "variants" / "broken.yaml").write_text("{[not yaml")
    _write_variants(data, [{"id": "a"}])
    assert [m["model_key"] for m in model_state.list_models(data)] == [
        "renault_megane_4"]
