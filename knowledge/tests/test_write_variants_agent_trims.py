"""write_variants — agent-supplied trims (B23).

TR_MARKET_TRIMS is a hardcoded per-model dict: onboarding a car means a human
hand-types a Python literal, which CLAUDE.md's scalability rule forbids. A
subscription agent researches the lineup instead and injects the same rows, so
`run()` takes `trims=` and the row builder must tolerate figures the agent
could not source.

The contract:
  - `validate_trims` rejects rows that are structurally wrong (unknown fuel,
    inverted years, missing identity keys) — deterministic checks only.
  - A figure the agent could not source is NOT an error. The row is written
    with `draft: true`, sync skips it, and the coverage report surfaces it.
    Never guess (CLAUDE.md automation principle: fail open).
  - Complete rows are byte-identical to what the hardcoded path produced, so
    already-onboarded cars are untouched.
"""

import pytest

from knowledge.catalog import write_variants as wv

_SHARED = {"electrical_code": "meg4_elec", "body_code": "meg4_body"}


def _trim(**over):
    t = {
        "id": "meg4_k9k_110", "generation": "IV", "engine_code": "K9K",
        "engine_family": "k9k_110", "fuel": "diesel", "displacement_cc": 1461,
        "power_min_hp": 110, "power_max_hp": 110, "transmission": "manual",
        "transmission_code": "manual", "year_from": 2016, "year_to": 2020,
        "notes": "1.5 dCi 110",
    }
    t.update(over)
    for k in [k for k, v in t.items() if v is _OMIT]:
        del t[k]
    return t


_OMIT = object()


# ── validate_trims ────────────────────────────────────────────────────────────


def test_complete_trim_validates_clean():
    assert wv.validate_trims([_trim()]) == []


def test_unknown_fuel_is_rejected():
    errs = wv.validate_trims([_trim(fuel="plutonium")])
    assert errs and "fuel" in errs[0]


def test_missing_identity_key_is_rejected():
    errs = wv.validate_trims([_trim(engine_family=_OMIT)])
    assert errs and "engine_family" in errs[0]


def test_year_to_before_year_from_is_rejected():
    errs = wv.validate_trims([_trim(year_from=2020, year_to=2016)])
    assert errs and "year" in errs[0].lower()


def test_open_ended_year_to_is_allowed():
    assert wv.validate_trims([_trim(year_to=None)]) == []


def test_inverted_power_range_is_rejected():
    errs = wv.validate_trims([_trim(power_min_hp=130, power_max_hp=90)])
    assert errs and "power" in errs[0].lower()


def test_unknown_transmission_is_rejected():
    errs = wv.validate_trims([_trim(transmission="cvt-ish")])
    assert errs and "transmission" in errs[0]


def test_unknown_emissions_value_is_rejected():
    errs = wv.validate_trims([_trim(emissions="euro9")])
    assert errs and "emissions" in errs[0]


def test_unsourced_power_is_not_an_error():
    """Fail open: the agent omits what it cannot source, it does not guess."""
    assert wv.validate_trims([_trim(power_min_hp=_OMIT, power_max_hp=_OMIT)]) == []


def test_errors_name_the_offending_trim_id():
    errs = wv.validate_trims([_trim(id="meg4_bad", fuel="steam")])
    assert "meg4_bad" in errs[0]


# ── build_rows: draft fail-open ───────────────────────────────────────────────


def test_row_without_power_is_marked_draft():
    rows = wv.build_rows("renault", "megane_4",
                         [_trim(power_min_hp=_OMIT, power_max_hp=_OMIT)], _SHARED)
    assert rows[0]["draft"] is True
    assert rows[0]["power_min_hp"] is None


def test_row_without_displacement_is_marked_draft():
    rows = wv.build_rows("renault", "megane_4",
                         [_trim(displacement_cc=_OMIT)], _SHARED)
    assert rows[0]["draft"] is True


def test_complete_row_carries_no_draft_key():
    """Regression guard: already-onboarded cars must be untouched."""
    rows = wv.build_rows("renault", "megane_4", [_trim()], _SHARED)
    assert "draft" not in rows[0]


def test_open_ended_year_to_does_not_make_a_row_draft():
    """year_to: None means 'still in production', not 'unsourced'."""
    rows = wv.build_rows("renault", "megane_4", [_trim(year_to=None)], _SHARED)
    assert "draft" not in rows[0]


def test_missing_optional_prose_fields_do_not_crash():
    rows = wv.build_rows("renault", "megane_4",
                         [_trim(notes=_OMIT, generation=_OMIT)], _SHARED)
    assert rows[0]["notes"] == ""
    assert rows[0]["generation"] is None


# ── run(trims=...) injection ──────────────────────────────────────────────────


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    variants, fitment = tmp_path / "variants", tmp_path / "fitment"
    variants.mkdir()
    fitment.mkdir()
    monkeypatch.setattr(wv, "VARIANTS_DIR", variants)
    monkeypatch.setattr(wv, "FITMENT_DIR", fitment)
    monkeypatch.setattr(wv, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(wv, "_cross_check", lambda *a, **k: None)
    return variants, fitment


def test_injected_trims_write_variants_and_fitment(catalog):
    variants, fitment = catalog
    wv.run("renault", "megane_4", trims=[_trim()])
    text = (variants / "renault_megane_4.yaml").read_text()
    assert "meg4_k9k_110" in text
    assert "meg4_k9k_110" in (fitment / "renault_megane_4.yaml").read_text()


def test_injected_trims_need_no_hardcoded_entry(catalog):
    """The whole point: a model absent from TR_MARKET_TRIMS still onboards."""
    assert "renault_brandnew" not in wv.TR_MARKET_TRIMS
    wv.run("renault", "brandnew", trims=[_trim(id="bn_1")])
    assert "bn_1" in (catalog[0] / "renault_brandnew.yaml").read_text()


def test_run_without_trims_still_reads_the_hardcoded_table(catalog):
    """Back-compat: the CLI path is unchanged."""
    with pytest.raises(SystemExit):
        wv.run("renault", "no_such_model")
