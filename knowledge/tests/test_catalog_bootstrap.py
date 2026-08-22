"""knowledge/catalog/wikipedia_articles.yaml — the onboarding bootstrap data.

This file replaced two hand-maintained Python dicts (_WIKIPEDIA_ARTICLE_TITLES,
_ENGINE_ALIASES). It is data rather than a catalog-derived lookup because
discover.py runs *before* a model has a catalog row — see the YAML's own header.
These tests lock the contract the loader has to keep.
"""
import yaml

from knowledge.catalog import discover


def test_bootstrap_yaml_parses_with_both_sections():
    data = yaml.safe_load(discover._BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    assert isinstance(data["articles"], dict) and data["articles"]
    assert isinstance(data["engine_aliases"], dict) and data["engine_aliases"]


def test_article_titles_survive_the_move_off_python():
    # The exact values the Python literal held before the move.
    for key, title in {
        "renault_megane_4":    "Renault Mégane",
        "renault_clio_5":      "Renault Clio",
        "volkswagen_golf_7":   "Volkswagen Golf Mk7",
        "volkswagen_golf_8":   "Volkswagen Golf Mk8",
        "toyota_corolla_12":   "Toyota Corolla (E210)",
        "ford_focus_3":        "Ford Focus (third generation)",
        "kia_sportage_4":      "Kia Sportage",
    }.items():
        assert discover.wikipedia_article_title(key) == title, key


def test_unlisted_model_returns_none_so_the_caller_can_guess():
    # fetch_model_catalog builds "Make Model" from the key when this is None;
    # an unlisted model must degrade to a guess, never raise.
    assert discover.wikipedia_article_title("mazda_cx_5") is None


def test_engine_aliases_map_nissan_codes_to_market_codes():
    for printed, market in {"h5dt": "h5d", "h5ft": "h5f", "h5ht": "h5h",
                            "m5mt": "m5m", "m5pt": "m5p"}.items():
        assert discover.engine_alias(printed) == market, printed


def test_code_without_an_alias_falls_through_to_itself():
    assert discover.engine_alias("k9k") is None


def test_onboarding_needs_no_python_edit():
    """The point of the whole change: the module must hold no per-model dict."""
    src = discover.__file__
    text = open(src, encoding="utf-8").read()
    assert "_WIKIPEDIA_ARTICLE_TITLES" not in text
    assert "_ENGINE_ALIASES" not in text
