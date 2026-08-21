"""ops.reports.demand — mine no_match analyses into an onboarding demand queue.

Task 3 / backlog B10: logs/analyses.jsonl records every /analyze request; the
no_match ones are latent onboarding demand (cars Kriko doesn't cover, or covered
cars falling through a catalog year/fuel hole). This aggregates them into a
make/model table with a reason classification, so onboarding is data-driven.

Catalog membership (catalog_gap vs not_onboarded) is derived from
backend/data/variants/*.yaml via normalize.py's helpers — no hardcoded car names
(CLAUDE.md scalability principle). Tests here point that lookup at a small
_fresh_catalog_cache fixture catalog (renault/megane, renault/clio,
volkswagen/golf) instead of the real repo catalog, so onboarding a new make or
model later cannot change these assertions (review finding 3).
"""

import json

import pytest
import yaml

import backend.core.normalize as normalize_module
from ops.reports.demand import main, mine

# A small, self-contained catalog used only by tests — deliberately NOT the
# real backend/data/variants/*.yaml, so these tests stay green regardless of
# what gets onboarded to the live catalog. "testmake"/"testmodel" exists only
# here (see test_catalog_membership_uses_fixture_not_real_repo_catalog) as
# proof the fixture, not the real catalog, is what's being read.
_FIXTURE_CATALOG = {
    "renault.yaml": [
        {"make": "renault", "model": "megane"},
        {"make": "renault", "model": "clio"},
    ],
    "volkswagen.yaml": [
        {"make": "volkswagen", "model": "golf"},
    ],
    "testmake.yaml": [
        {"make": "testmake", "model": "testmodel"},
    ],
}


@pytest.fixture(autouse=True)
def _fresh_catalog_cache(tmp_path_factory, monkeypatch):
    """Point normalize.py's catalog reader at a small fixture catalog.

    Onboarding a real make/model must never be able to flip these tests
    (review finding 3) — so instead of clearing the cache and re-reading the
    real backend/data/variants/*.yaml, this monkeypatches the module-level
    _VARIANTS_DIR normalize.py's _catalog_makes_models() globs, and points it
    at a temp dir holding only the fixture rows above.
    """
    catalog_dir = tmp_path_factory.mktemp("fixture_variants_catalog")
    for filename, rows in _FIXTURE_CATALOG.items():
        (catalog_dir / filename).write_text(yaml.safe_dump(rows))
    monkeypatch.setattr(normalize_module, "_VARIANTS_DIR", catalog_dir)
    normalize_module._catalog_makes_models.cache_clear()
    yield
    normalize_module._catalog_makes_models.cache_clear()


def _rec(make, model, year, fuel, tx, method, notes, variant_ids=None, listing_url=None):
    # variant_ids defaults to [] (matches matcher.py's MatchResult for
    # no_match/inconsistent_listing); exact/ambiguous callers pass explicit ids
    # so the fixture matches the real record shape (backend/api/main.py logs
    # variant_ids alongside method/notes).
    return {
        "match": {"method": method, "notes": notes, "variant_ids": variant_ids or []},
        "ad_metadata": {
            "make": make, "model": model, "year": year,
            "fuel_type": fuel, "transmission": tx,
        },
        "listing_url": listing_url,
    }


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


# ── reason classification (the three classes) ────────────────────────────────

def test_classifies_not_onboarded(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020."),
    ])
    groups, skipped = mine(p)
    assert skipped == 0
    assert len(groups) == 1
    assert groups[0].reason == "not_onboarded"
    assert groups[0].make == "Audi"
    assert groups[0].model == "Q2"


def test_not_onboarded_wins_even_when_some_notes_are_missing_fields(tmp_path):
    # Audi Q2 isn't onboarded at all; a Missing-required-fields note on one of its
    # records must not demote the group to missing_fields — the onboarding signal
    # is that we don't cover Audi Q2, period.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2024, "Gasoline", "S-Tronic", "no_match",
             "Missing required fields: ['fuel']"),
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020."),
    ])
    groups, _ = mine(p)
    assert groups[0].reason == "not_onboarded"


def test_classifies_catalog_gap_megane_2024(tmp_path):
    # Renault Megane IS onboarded but the petrol year window ends before 2024.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Renault", "Megane", 2024, "Benzinli", "EDC", "no_match",
             "No renault megane petrol for 2024."),
    ])
    groups, _ = mine(p)
    assert groups[0].reason == "catalog_gap"
    assert groups[0].years == [2024]


def test_classifies_missing_fields(tmp_path):
    # VW Golf IS onboarded (vw -> volkswagen), but every record failed before a
    # match could be attempted — required fields absent, not a catalog hole.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("VW", "Golf", None, None, None, "no_match",
             "Missing required fields: ['fuel', 'year']"),
    ])
    groups, _ = mine(p)
    assert groups[0].reason == "missing_fields"


def test_classification_derives_missing_fields_from_ad_metadata_not_notes_text(tmp_path):
    # Review finding 2: matcher.py's free-text notes prefix must not be
    # sniffed to decide missing_fields vs catalog_gap. This record's
    # ad_metadata actually has make/model/year/fuel ALL present (matching
    # matcher.py's own hard-filter requirement), even though the notes text
    # happens to say "Missing required fields" (e.g. stale/incorrect logging,
    # or matcher.py's wording changes independently). Since the metadata is
    # complete for an onboarded model, this must classify as catalog_gap, not
    # missing_fields.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Renault", "Megane", 2024, "Benzinli", "EDC", "no_match",
             "Missing required fields: ['fuel']"),
    ])
    groups, _ = mine(p)
    assert groups[0].reason == "catalog_gap"


def test_classification_flags_missing_fields_even_when_notes_text_says_otherwise(tmp_path):
    # Review finding 2, converse case: ad_metadata genuinely lacks a required
    # field (year is None) even though the notes text doesn't mention
    # "Missing required fields" at all. Classification must catch this from
    # the metadata itself — matcher.py's own hard filter needs make/model/
    # fuel/year all present — not from notes wording.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Volkswagen", "Golf", None, "Gasoline", "DSG", "no_match",
             "No match found."),
    ])
    groups, _ = mine(p)
    assert groups[0].reason == "missing_fields"


def test_catalog_membership_uses_fixture_not_real_repo_catalog(tmp_path):
    # Review finding 3: proves _fresh_catalog_cache's monkeypatch is actually
    # wired in. "testmake"/"testmodel" exists only in the fixture catalog
    # (never in the real backend/data/variants/*.yaml) — if this test were
    # reading the real catalog it would see an unknown make and classify as
    # not_onboarded instead of catalog_gap.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("TestMake", "TestModel", 2024, "Gasoline", "Automatic", "no_match",
             "No testmake testmodel petrol for 2024."),
    ])
    groups, _ = mine(p)
    assert groups[0].reason == "catalog_gap"


# ── the (unscraped) bucket for missing make/model ────────────────────────────

def test_missing_make_grouped_under_unscraped_bucket(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec(None, "Golf", 2016, None, None, "no_match",
             "Missing required fields: ['make', 'fuel']"),
    ])
    groups, _ = mine(p)
    assert groups[0].make == "(unscraped)"
    assert groups[0].model == "Golf"
    assert groups[0].reason == "missing_fields"


# ── malformed JSONL is skipped, not fatal ────────────────────────────────────

def test_skips_malformed_lines_and_reports_count(tmp_path):
    p = tmp_path / "a.jsonl"
    good = json.dumps(_rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
                           "No audi q2 diesel for 2020."))
    # A truncated line, a blank line (ignored, not counted), then two good ones.
    p.write_text(good + "\n" + "{not valid json\n" + "\n" + good + "\n")
    groups, skipped = mine(p)
    assert skipped == 1
    assert len(groups) == 1
    assert groups[0].count == 2


def test_missing_file_does_not_crash(tmp_path):
    groups, skipped = mine(tmp_path / "nope.jsonl")
    assert groups == []
    assert skipped == 0


def test_skips_non_dict_json_lines_and_reports_count(tmp_path):
    # Review finding 1: a line can be *valid JSON* but not an object — a bare
    # number, null, string, or array. _read_records must treat these as
    # malformed (skip + count) rather than pass them through to mine(), which
    # otherwise crashes on rec.get("match") with AttributeError.
    p = tmp_path / "a.jsonl"
    p.write_text('42\nnull\n"just a string"\n[1,2,3]\n')
    groups, skipped = mine(p)
    assert groups == []
    assert skipped == 4


# ── selection, aggregation, sort, limit ──────────────────────────────────────

def test_only_no_match_records_selected(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020."),
        _rec("Renault", "Clio", 2020, "diesel", "manual", "exact", "matched",
             variant_ids=["clio5_k9k_85"]),
        _rec("Volkswagen", "Golf", 2011, "Dizel", "DSG", "ambiguous", "Ambiguous",
             variant_ids=["golf7_ea211", "golf7_ea288"]),
    ])
    groups, _ = mine(p)
    assert len(groups) == 1
    assert groups[0].make == "Audi"


def test_selection_keys_on_empty_variant_ids_not_the_literal_method_string(tmp_path):
    # matcher.py's "inconsistent_listing" (implausible cc/hp for any candidate)
    # is a distinct method string from "no_match" but is exactly the same
    # "produced no variants" signal — the brief asks us to key selection on
    # variant_ids being empty, not hand-match "no_match" alone, so a future
    # failure-method string is still picked up with no code change here.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "inconsistent_listing",
             "Listing (cc=1000, hp=999) matches no real audi q2 diesel variant."),
    ])
    groups, _ = mine(p)
    assert len(groups) == 1
    assert groups[0].make == "Audi"


def test_analyze_crash_record_not_counted_as_demand(tmp_path):
    # backend/api/main.py logs match=None when /analyze raised before matching
    # ran at all (e.g. a DB error) — that's a server fault, not "this car isn't
    # covered", so it must not be mined as onboarding demand.
    p = tmp_path / "a.jsonl"
    crash = {
        "match": None,
        "ad_metadata": {"make": "Audi", "model": "Q2"},
        "error": "db connection refused",
    }
    p.write_text(json.dumps(crash) + "\n")
    groups, skipped = mine(p)
    assert groups == []
    assert skipped == 0


def test_groups_merge_across_make_spelling_aliases(tmp_path):
    # "VW" and "Volkswagen" are the same real make (normalize.py's _MAKE_ALIASES)
    # — grouping must go through the catalog-aware normalize helpers, not raw
    # lowercasing, or the same real-world demand fragments into two rows and
    # undercounts (this exact split is present in the real analyses.jsonl log).
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("VW", "Golf", None, None, None, "no_match",
             "Missing required fields: ['fuel', 'year']"),
        _rec("Volkswagen", "Golf", 2015, "Gasoline", None, "no_match",
             "Missing required fields: ['fuel']"),
    ])
    groups, _ = mine(p)
    assert len(groups) == 1
    assert groups[0].count == 2
    assert groups[0].model == "Golf"


def test_aggregates_years_fuels_transmissions_case_insensitive_grouping(tmp_path):
    # "renault"/"Renault" and "clio "/"Clio" must collapse into one group.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Renault", "Clio", 2014, "Benzinli", "Manuel", "no_match",
             "No renault clio petrol for 2014."),
        _rec("renault", "clio ", 2015, "Dizel", "Manuel", "no_match",
             "No renault clio diesel for 2015."),
    ])
    groups, _ = mine(p)
    assert len(groups) == 1
    g = groups[0]
    assert g.count == 2
    assert g.years == [2014, 2015]
    assert set(g.fuels) == {"Benzinli", "Dizel"}
    assert set(g.transmissions) == {"Manuel"}
    assert g.reason == "catalog_gap"


def _mixed_counts_records():
    recs = [_rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
                 "No audi q2 diesel for 2020.")]                      # count 1
    recs += [_rec("BMW", "3 Series", 2012, "Diesel", "Otomatik", "no_match",
                  "No bmw 3series diesel for 2012.")] * 3             # count 3
    recs += [_rec("Citroen", "Berlingo", 2025, "Diesel", "Manuel", "no_match",
                  "No citroen berlingo diesel for 2025.")] * 2       # count 2
    return recs


def test_sorted_by_count_descending(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, _mixed_counts_records())
    groups, _ = mine(p)
    assert [g.count for g in groups] == [3, 2, 1]
    assert groups[0].model == "3 Series"
    assert groups[-1].model == "Q2"


def test_limit_caps_rows_to_top_n(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, _mixed_counts_records())
    groups, _ = mine(p, limit=2)
    assert len(groups) == 2
    assert [g.count for g in groups] == [3, 2]


# ── example listing URL per group (brief requirement #1's output spec) ──────

def test_group_carries_example_listing_url(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020.",
             listing_url="https://www.sahibinden.com/ilan/audi-q2-1"),
    ])
    groups, _ = mine(p)
    assert groups[0].example_url == "https://www.sahibinden.com/ilan/audi-q2-1"


def test_example_url_is_first_seen_non_null_in_group(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020.", listing_url=None),
        _rec("Audi", "Q2", 2021, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2021.",
             listing_url="https://www.sahibinden.com/ilan/audi-q2-2"),
        _rec("Audi", "Q2", 2022, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2022.",
             listing_url="https://www.sahibinden.com/ilan/audi-q2-3"),
    ])
    groups, _ = mine(p)
    assert groups[0].example_url == "https://www.sahibinden.com/ilan/audi-q2-2"


def test_example_url_none_when_no_record_in_group_has_one(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020.", listing_url=None),
    ])
    groups, _ = mine(p)
    assert groups[0].example_url is None


def test_main_table_includes_example_url(tmp_path, capsys):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020.",
             listing_url="https://www.sahibinden.com/ilan/audi-q2-1"),
    ])
    main(["--log", str(p)])
    out = capsys.readouterr().out
    assert "https://www.sahibinden.com/ilan/audi-q2-1" in out


# ── CLI entrypoint renders a table ───────────────────────────────────────────

def test_main_prints_table(tmp_path, capsys):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Audi", "Q2", 2020, "Diesel", "S-Tronic", "no_match",
             "No audi q2 diesel for 2020."),
    ])
    main(["--log", str(p)])
    out = capsys.readouterr().out
    assert "Audi" in out
    assert "Q2" in out
    assert "not_onboarded" in out


# ── review minors: display casing + table alignment ──────────────────────────

def test_group_display_uses_most_common_raw_casing(tmp_path):
    # Review minor: a group merges by normalized slug, so it can contain several
    # raw spellings ("vw" and "Volkswagen"). It must display the MOST FREQUENT
    # raw form, not whichever was logged first — a lone leading "vw" ahead of
    # three "Volkswagen"s must still read "Volkswagen".
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("vw", "Golf", 2015, "Gasoline", "DSG", "no_match", "gap"),
        _rec("Volkswagen", "Golf", 2016, "Gasoline", "DSG", "no_match", "gap"),
        _rec("Volkswagen", "Golf", 2017, "Gasoline", "DSG", "no_match", "gap"),
        _rec("Volkswagen", "Golf", 2018, "Gasoline", "DSG", "no_match", "gap"),
    ])
    groups, _ = mine(p)
    assert len(groups) == 1
    assert groups[0].count == 4
    assert groups[0].make == "Volkswagen"  # majority form, not first-seen "vw"


def test_table_columns_stay_aligned_when_years_overflow_default_width(tmp_path, capsys):
    # Review minor: YEARS/FUELS used hardcoded 26/20-char widths, so a long year
    # list shoved every later column out of alignment. Widths are now derived
    # from the data — the FUELS header must sit exactly above the FUELS cell even
    # when the YEARS string is far longer than the old 26-char cap.
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _rec("Renault", "Megane", y, "ZZFUEL", "EDC", "no_match", "gap")
        for y in range(2000, 2013)  # 13 years → YEARS string well over 26 chars
    ])
    main(["--log", str(p)])
    out = capsys.readouterr().out
    header, row = out.splitlines()[0], out.splitlines()[1]
    assert len(", ".join(str(y) for y in range(2000, 2013))) > 26  # guards the premise
    assert header.index("FUELS") == row.index("ZZFUEL")  # column aligned, not shoved
