"""_find_make_model_for_part must return the FULL model slug, including any
generation suffix (golf_7, megane_4, clio_5) — not just the first token after
make.

Regression: this returned model="golf" for part_id="ea888" (truncating
"volkswagen_golf_7" at the first underscore). Every caller reassembles
f"{make}_{model}.yaml" to find the variants file — auto.py's and
process.py's run_part() both use this to call ensure_part_stub() before
writing claims. The truncated name never matched a real file, so
ensure_part_stub() silently never ran, and write_promoted_part_claims wrote
a part YAML missing part_id/part_type/display_name/manufacturer entirely
(see docs/design_flaws.md Flaw 2 postmortem — this bug hit the ea888 merge
in production before being caught).
"""

from pathlib import Path

from knowledge.parts.search_templates import _find_make_model_for_part, templates_for_part

REPO_ROOT = Path(__file__).parent.parent.parent
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"


def test_resolves_full_model_slug_with_generation_suffix():
    make, model = _find_make_model_for_part("ea888", "engine")
    assert (make, model) == ("volkswagen", "golf_7")


def test_resolved_model_reassembles_to_a_real_variants_file():
    make, model = _find_make_model_for_part("ea888", "engine")
    variants_path = VARIANTS_DIR / f"{make}_{model}.yaml"
    assert variants_path.exists(), (
        f"{variants_path} must exist — this is exactly the path "
        f"ensure_part_stub()'s callers construct to load variants"
    )


def test_resolves_full_model_slug_for_renault_parts():
    # Power-split legacy ids merged into family parts at the B16 swap: the
    # catalog now serves k9k (covering k9k_85/90/100/110), not the per-power
    # files. clio_5 sorts before megane_4 in fitment scan order.
    make, model = _find_make_model_for_part("k9k", "engine")
    assert (make, model) == ("renault", "clio_5")
    variants_path = VARIANTS_DIR / f"{make}_{model}.yaml"
    assert variants_path.exists()


def test_search_query_text_has_no_stray_underscore():
    templates = templates_for_part("k9k", "engine", {"fuel": "diesel"})
    queries = [q for _domain, q in templates]
    assert any("Clio 5" in q for q in queries)
    assert not any("_" in q for q in queries)
