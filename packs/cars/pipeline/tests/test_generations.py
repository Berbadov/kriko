"""generations — the researched generation lineup for one make+model (B23).

Kriko's model keys carry a generation (`megane_4`, `golf_7`), but the demand
queue only knows make/model/year from scraped listings. So onboarding is two
phases: an agent researches which generations exist, then you pick one.

This module owns that lineup: deterministic validation, and writing it to
`packs/cars/pipeline/catalog/generations/{make}_{model}.yaml`. Same contract as the trim
lineup — the agent supplies data through a validated tool, never a file.

Phase 1 also resolves the scrape's dirty display name ("VW CC 1.4 TSI") to a
canonical slug, which is why it has to happen before you can pick anything.
"""

import pytest
import yaml

from packs.cars.pipeline.catalog import generations as g


def _gen(**over):
    d = {"generation": 1, "name": "I (GA)", "year_from": 2016, "year_to": 2023,
         "source_urls": ["https://example.invalid/q2"]}
    d.update(over)
    return {k: v for k, v in d.items() if v is not _OMIT}


_OMIT = object()


# ── slugify ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,slug", [
    ("Q2", "q2"),
    ("VW CC 1.4 TSI", "vw_cc_1_4_tsi"),
    ("3 Series", "3_series"),
    ("  Mégane  ", "megane"),
    ("A4/Avant", "a4_avant"),
    ("C-Class", "c_class"),
])
def test_slugify_produces_catalog_shaped_keys(raw, slug):
    assert g.slugify(raw) == slug


def test_slugify_collapses_repeats_and_trims_edges():
    assert g.slugify("--Golf   GTI--") == "golf_gti"


def test_slugify_of_junk_is_empty_not_garbage():
    assert g.slugify("!!!") == ""


# ── validate_generations ──────────────────────────────────────────────────────


def test_valid_lineup_passes():
    assert g.validate_generations([_gen(), _gen(generation=2, year_from=2024,
                                        year_to=None)]) == []


def test_empty_lineup_is_rejected():
    assert g.validate_generations([])


def test_generation_must_be_a_positive_int():
    assert any("generation" in e for e in g.validate_generations([_gen(generation=0)]))
    assert any("generation" in e for e in g.validate_generations([_gen(generation="IV")]))


def test_duplicate_generation_numbers_are_rejected():
    errs = g.validate_generations([_gen(), _gen(name="dupe")])
    assert any("duplicate" in e for e in errs)


def test_year_from_is_required():
    assert any("year_from" in e for e in g.validate_generations([_gen(year_from=_OMIT)]))


def test_year_to_before_year_from_is_rejected():
    errs = g.validate_generations([_gen(year_from=2020, year_to=2016)])
    assert any("year" in e.lower() for e in errs)


def test_open_ended_year_to_is_allowed():
    assert g.validate_generations([_gen(year_to=None)]) == []


def test_implausible_years_are_rejected():
    assert g.validate_generations([_gen(year_from=1780)])
    assert g.validate_generations([_gen(year_from=2400)])


def test_a_generation_needs_at_least_one_source():
    errs = g.validate_generations([_gen(source_urls=[])])
    assert any("source" in e for e in errs)


def test_errors_name_the_offending_generation():
    errs = g.validate_generations([_gen(generation=3, source_urls=[])])
    assert any("3" in e for e in errs)


# ── write / read ──────────────────────────────────────────────────────────────


@pytest.fixture
def gdir(tmp_path):
    d = tmp_path / "generations"
    d.mkdir()
    return d


def test_write_then_read_round_trips(gdir):
    out = g.write_generations("audi", "q2", [_gen()], gdir)
    assert out["model_key"] == "audi_q2"
    assert out["generations"] == 1
    back = g.read_generations("audi", "q2", gdir)
    assert back["make"] == "audi" and back["model"] == "q2"
    assert back["generations"][0]["generation"] == 1


def test_write_rejects_an_invalid_lineup_without_writing(gdir):
    out = g.write_generations("audi", "q2", [_gen(year_from=_OMIT)], gdir)
    assert out["errors"]
    assert not (gdir / "audi_q2.yaml").exists()


def test_read_returns_none_when_not_researched(gdir):
    assert g.read_generations("audi", "q2", gdir) is None


def test_canonical_model_is_written_under_its_own_key(gdir):
    """'VW CC 1.4 TSI' is a scrape artifact; the agent resolves it."""
    out = g.write_generations("volkswagen", "vw_cc_1_4_tsi", [_gen()], gdir,
                              canonical_model="passat_cc")
    assert out["model_key"] == "volkswagen_passat_cc"
    assert (gdir / "volkswagen_passat_cc.yaml").exists()


def test_a_queried_alias_still_finds_the_canonical_lineup(gdir):
    g.write_generations("volkswagen", "vw_cc_1_4_tsi", [_gen()], gdir,
                        canonical_model="passat_cc")
    found = g.read_generations("volkswagen", "vw_cc_1_4_tsi", gdir)
    assert found is not None
    assert found["model"] == "passat_cc"


def test_generation_rows_carry_their_onboarding_model_key(gdir):
    g.write_generations("audi", "q2", [_gen(), _gen(generation=2,
                                                    year_from=2024, year_to=None)], gdir)
    back = g.read_generations("audi", "q2", gdir)
    assert [x["model_key"] for x in back["generations"]] == ["q2_1", "q2_2"]


def test_rewrite_replaces_the_lineup(gdir):
    g.write_generations("audi", "q2", [_gen()], gdir)
    g.write_generations("audi", "q2", [_gen(generation=2, year_from=2024,
                                            year_to=None)], gdir)
    back = g.read_generations("audi", "q2", gdir)
    assert [x["generation"] for x in back["generations"]] == [2]


def test_written_file_is_plain_yaml(gdir):
    g.write_generations("audi", "q2", [_gen()], gdir)
    raw = yaml.safe_load((gdir / "audi_q2.yaml").read_text(encoding="utf-8"))
    assert raw["make"] == "audi"
    assert isinstance(raw["generations"], list)
