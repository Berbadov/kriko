"""normalize_make/normalize_model — catalog-derived, not hand-mapped.

Regression coverage for the de-hardcoding described in CLAUDE.md's scalability
principle: _MAKE_MAP/_MODEL_MAP used to be fixed dicts capping recognition at
whatever a human remembered to type in. They're now derived from
backend/data/variants/*.yaml (same pattern as knowledge/stoplists.py's
catalog_code_manufacturers()), with a generic slugify fallback for anything not
yet onboarded — normalization must never return None just because a make/model
isn't in the catalog yet (that's matcher.py's DB query's job to fail-open on).
"""

import pytest

from backend.core.normalize import _catalog_makes_models, normalize_make, normalize_model


@pytest.fixture(autouse=True)
def _fresh_catalog_cache():
    _catalog_makes_models.cache_clear()
    yield
    _catalog_makes_models.cache_clear()


def test_normalize_make_known_catalog_entry():
    assert normalize_make("Renault") == "renault"
    assert normalize_make("volkswagen") == "volkswagen"


def test_normalize_make_alias():
    assert normalize_make("VW") == "volkswagen"
    assert normalize_make("Mercedes-Benz") == "mercedes"


def test_normalize_make_accent_stripped_via_slugify():
    assert normalize_make("Citroën") == "citroen"


def test_normalize_model_accent_stripped_via_slugify():
    assert normalize_model("Mégane") == "megane"


def test_normalize_model_hyphen_stripped_via_slugify():
    assert normalize_model("C-HR") == "chr"


def test_normalize_make_not_in_catalog_still_returns_a_slug_not_none():
    # Toyota has no backend/data/variants/*.yaml yet — must fail-open (return a
    # slug matcher.py's DB query can safely find zero rows for), not fail-closed.
    assert normalize_make("Toyota") == "toyota"
    assert normalize_model("Corolla") == "corolla"


def test_normalize_make_empty_input_is_none():
    assert normalize_make(None) is None
    assert normalize_make("") is None
    assert normalize_model(None) is None


def test_catalog_makes_models_derived_from_real_variants_yaml():
    makes, models = _catalog_makes_models()
    assert "renault" in makes
    assert "volkswagen" in makes
    assert "megane" in models
    assert "golf" in models
