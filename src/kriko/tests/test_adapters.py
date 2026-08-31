"""Scraped page -> query, using rules a pack supplies.

Two things are being defended here.

**Site knowledge belongs to a pack.** The old `/analyze` knew about Sahibinden;
this knows about adapters, and the cars pack knows about Sahibinden. A new
listing site is a JSON file.

**A wrong number is worse than a missing one.** Scraped values lie in a
specific way — a run of digits with a locale's grouping separator can look
like a different magnitude depending on which field it landed in — so range
bounds decide what is believable, and anything outside them is dropped
rather than trusted. A missing value fails open and says so; a confidently
wrong one silently answers about a different product.
"""

import json

from kriko.adapters import (adapt, adapter_for, identity_vocabulary,
                            load_adapters)

SPEC = {
    "id": "demo",
    "subject_kind": "product",
    "match": ["*example.com/ilan/*"],
    "identity": {
        "brand": {"labels": ["marka", "brand"]},
        "max_torque_nm": {"labels": ["tork"], "parse": "int_range",
                          "min": 1, "max": 200},
        "released": {"labels": ["yıl", "year"], "parse": "int_range",
                     "min": 1980, "max": 2035},
    },
    "context": {
        "charge_cycles": {"labels": ["şarj", "cycles"], "parse": "int_range",
                          "min": 0, "max": 2000},
        "free_text": {"from": "description"},
    },
    "derive": [{"key": "age_years", "op": "years_since", "from": "released"}],
    "ignore_labels": ["renk"],
}


# ── which site is this? ──────────────────────────────────────────────────

def test_url_patterns_match_with_globs(tmp_path):
    from kriko.store import packstore
    from kriko.store.db import connect

    store = connect(tmp_path / "s.sqlite")
    with store:
        packstore.write_pack_row(store, pack_id="p", name="P", version="1",
                                 content_digest="x")
        store.execute("UPDATE packs SET enabled = 1")
        store.execute("INSERT INTO pack_assets VALUES (?,?,?,?)",
                      ("p", "adapters/demo.json", "adapter", json.dumps(SPEC)))

    assert adapter_for(store, "https://example.com/ilan/car-1")["id"] == "demo"
    assert adapter_for(store, "https://elsewhere.org/thing") is None
    store.close()


def test_a_broken_adapter_does_not_break_the_others(tmp_path):
    """One pack shipping malformed JSON must not blind the browser everywhere."""
    from kriko.store import packstore
    from kriko.store.db import connect

    store = connect(tmp_path / "s.sqlite")
    with store:
        packstore.write_pack_row(store, pack_id="p", name="P", version="1",
                                 content_digest="x")
        store.execute("INSERT INTO pack_assets VALUES (?,?,?,?)",
                      ("p", "adapters/broken.json", "adapter", "{not json"))
        store.execute("INSERT INTO pack_assets VALUES (?,?,?,?)",
                      ("p", "adapters/demo.json", "adapter", json.dumps(SPEC)))

    assert [a["id"] for a in load_adapters(store)] == ["demo"]
    store.close()


# ── reading labels ───────────────────────────────────────────────────────

def test_labels_match_regardless_of_case_colon_or_extra_words():
    got = adapt(SPEC, {"Marka:": "Makita", "Tork (Nm)": "162"})
    assert got.identity["brand"] == "Makita"
    assert got.identity["max_torque_nm"] == 162


def test_range_bounds_disambiguate_identical_digit_patterns():
    """A plain reading and a comma-grouped one both parse; each field's own
    range is what decides whether the result is believable."""
    got = adapt(SPEC, {"Tork": "162 Nm", "Şarj": "1,200"})
    assert got.identity["max_torque_nm"] == 162
    assert got.context["charge_cycles"] == 1200


def test_a_value_outside_its_range_is_dropped_rather_than_believed():
    """Fail open. A missing charge-cycle count downranks a claim and says why;
    a count of nine million would gate every interval claim wrongly and say
    nothing."""
    got = adapt(SPEC, {"Şarj": "9.000.000.000"})
    assert "charge_cycles" not in got.context


def test_a_field_the_page_does_not_have_is_simply_absent():
    got = adapt(SPEC, {"Marka": "Makita"})
    assert got.identity == {"brand": "Makita"}
    assert "charge_cycles" not in got.context


def test_text_fields_come_from_named_sources_not_labels():
    got = adapt(SPEC, {}, description="Tek elden, bakımlı")
    assert got.context["free_text"] == "Tek elden, bakımlı"


def test_derived_values_are_arithmetic_not_scraping():
    from datetime import date
    got = adapt(SPEC, {"Yıl": "2018"})
    assert got.context["age_years"] == date.today().year - 2018


def test_derivation_is_skipped_when_its_input_is_missing():
    assert "age_years" not in adapt(SPEC, {"Marka": "Makita"}).context


# ── coverage signal ──────────────────────────────────────────────────────

def test_labels_with_no_rule_are_reported_not_silently_dropped():
    """A site adding a useful field should be discoverable.

    Silently ignoring unknown labels is how an adapter rots: the page starts
    carrying something worth reading and nobody finds out for a year.
    """
    got = adapt(SPEC, {"Marka": "Makita", "Kimden": "Sahibinden",
                       "Takasa Uygun": "Evet"})
    assert got.unmapped == ("Kimden", "Takasa Uygun")


def test_explicitly_ignored_labels_are_not_reported_as_unmapped():
    """The difference between "we decided this is noise" and "nobody looked"."""
    assert adapt(SPEC, {"Renk": "Beyaz"}).unmapped == ()


# ── the boundary that matters ────────────────────────────────────────────

def test_the_adapter_format_has_no_executable_field():
    """A pack must never ship code that runs in a browser.

    Installing a pack would otherwise mean granting its author the ability to
    run JavaScript on every page the extension can see. The vocabulary here is
    label lists and parse hints; anything it cannot express is a reason to
    extend the interpreter in review, once, rather than to open that door.
    """
    import ast
    import inspect

    import kriko.adapters as module

    # Checked on the AST, not with substring search: `re.compile` legitimately
    # contains "compile(", and a guard that cries wolf on it gets deleted.
    tree = ast.parse(inspect.getsource(module))
    dangerous = {"eval", "exec", "compile", "__import__"}
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (called & dangerous), (
        f"kriko/adapters.py calls {sorted(called & dangerous)} — adapter content "
        "is data from an installed pack and must never be executed")


def test_an_unknown_parse_hint_falls_back_to_plain_text():
    """Forward compatibility: a newer pack must not crash an older engine."""
    spec = {"id": "x", "identity": {"a": {"labels": ["a"], "parse": "future_thing"}}}
    assert adapt(spec, {"a": " hello "}).identity["a"] == "hello"


def test_the_real_cars_adapter_reads_a_real_listing_shape():
    """The shape extension/content.js actually produces today.

    This exercises the cars pack's real, shipped
    `packs/cars/adapters/sahibinden.json` as a concrete example — the
    runner (`adapt`) itself is category-blind, but no other installed pack
    ships an adapter file, so there is nothing else to point this at. The
    make/model/fuel below are real cars-pack vocabulary on purpose, not a
    fixture to decontaminate.
    """
    from pathlib import Path
    spec = json.loads(Path("packs/cars/adapters/sahibinden.json")
                      .read_text(encoding="utf-8"))
    got = adapt(spec, {
        "Marka": "Renault", "Seri": "Megane", "Model": "1.5 dCi Joy",
        "Yıl": "2018", "Yakıt": "Dizel", "Vites": "Otomatik",
        "Motor Hacmi": "1.461 cm3", "Motor Gücü": "110 hp", "KM": "180.000",
        "Renk": "Beyaz",
    }, url="https://www.sahibinden.com/ilan/x")

    assert got.identity == {
        "make": "Renault", "model": "Megane", "fuel": "Dizel",
        "transmission": "Otomatik", "displacement_cc": 1461,
        "power_min_hp": 110, "build_year": 2018,
    }
    assert got.context["usage_km"] == 180_000
    # "Model" on Sahibinden is the trim, not the model — the model lives in
    # "Seri". Getting this backwards was a real bug in the old scraper.
    assert got.identity["model"] == "Megane"


# ── raw scrapes contain near-miss labels ─────────────────────────────────
#
# These land the moment the extension stops pre-filtering labels in
# JavaScript and posts the page's own label/value pairs (Phase 6c). The old
# scraper kept a hand-written exclusion in `content.js`; that logic belongs
# to the pack, not to the client, so it has to hold here instead.

def _cars_spec():
    from pathlib import Path
    return json.loads(Path("packs/cars/adapters/sahibinden.json")
                      .read_text(encoding="utf-8"))


def test_an_exact_label_beats_a_longer_one_that_merely_contains_it():
    """"Yakıt Tüketimi" must not answer for "Yakıt"."""
    got = adapt(_cars_spec(),
                {"Yakıt Tüketimi": "4,5 lt", "Yakıt": "Dizel"},
                url="https://www.sahibinden.com/ilan/x")
    assert got.identity["fuel"] == "Dizel"


def test_an_ignored_label_is_never_picked_even_when_a_rule_would_match_it():
    """Ignoring a label must mean *do not read it*, not merely *do not report
    it as unmapped*. Otherwise the only defence against a near-miss label is
    that some better label happened to exist on the page."""
    got = adapt(_cars_spec(),
                {"Yakıt Tüketimi": "4,5 lt"},
                url="https://www.sahibinden.com/ilan/x")
    assert "fuel" not in got.identity


# ── the page's own labels are not always readable ────────────────────────
#
# Sahibinden has redesigned its info-list markup repeatedly, and every
# redesign silently zeroed every field. The client used to paper over that
# with title-parsing heuristics; those are site knowledge, so they belong to
# the adapter. Two closed mechanisms cover it:
#
#   `from`       — a labelled rule may name a fallback text source.
#   `vocabulary` — "find a value this attribute is already known to take".
#
# The second is what keeps the make list out of Python. The values come from
# the pack's own rows, so a make is readable off a title the moment a subject
# using it exists, with nothing to register and nothing to forget.

TITLE_SPEC = {
    "id": "titles",
    "subject_kind": "product",
    "match": ["*example.com/*"],
    "identity": {
        "released": {"labels": ["yıl", "year"], "from": "title",
                     "parse": "int_range", "min": 1980, "max": 2035},
        "brand": {"labels": ["marka"], "from": "title", "vocabulary": "brand"},
    },
}


def test_a_labelled_rule_falls_back_to_a_text_source_when_no_label_matches():
    got = adapt(TITLE_SPEC, {}, title="2014 Makita DHP484 18V Brushless")
    assert got.identity["released"] == 2014


def test_the_label_still_wins_when_the_page_has_one():
    got = adapt(TITLE_SPEC, {"Yıl": "2016"}, title="2014 Makita DHP484")
    assert got.identity["released"] == 2016


def test_the_title_fallback_respects_the_range_and_invents_nothing():
    """"18" and "1.200 charge cycles" are not model years."""
    got = adapt(TITLE_SPEC, {}, title="Makita DHP484 18V 1.200 charge cycles")
    assert "released" not in got.identity


def _store_with_identity_values(tmp_path, rows):
    from kriko.store import packstore
    from kriko.store.db import connect

    store = connect(tmp_path / "s.sqlite")
    with store:
        packstore.write_pack_row(store, pack_id="p", name="P", version="1",
                                 content_digest="x")
        store.execute("INSERT INTO subjects VALUES ('s','p','product','S')")
        for n, (key, value) in enumerate(rows):
            store.execute(
                "INSERT INTO attributes (attribute_id, pack_id, subject_id,"
                " key, value_text, is_identity) VALUES (?,?,?,?,?,1)",
                (f"a{n}", "p", "s", key, value))
    return store


def test_a_vocabulary_rule_reads_a_value_the_pack_already_knows(tmp_path):
    store = _store_with_identity_values(
        tmp_path, [("brand", "makita"), ("brand", "einhell")])
    got = adapt(TITLE_SPEC, {}, title="2014 Makita DHP484 18V Brushless",
                vocabulary=identity_vocabulary(store))
    assert got.identity["brand"] == "makita"
    store.close()


def test_a_vocabulary_rule_prefers_the_longest_match(tmp_path):
    """"bosch professional" must not be read as "bosch"."""
    store = _store_with_identity_values(
        tmp_path, [("brand", "bosch"), ("brand", "bosch professional")])
    got = adapt(TITLE_SPEC, {}, title="2014 Bosch Professional GSR 18V",
                vocabulary=identity_vocabulary(store))
    assert got.identity["brand"] == "bosch professional"
    store.close()


def test_a_vocabulary_rule_with_no_installed_values_invents_nothing():
    got = adapt(TITLE_SPEC, {}, title="2014 Makita DHP484", vocabulary={})
    assert "brand" not in got.identity


def test_the_vocabulary_is_whatever_the_packs_declared_identity_on(tmp_path):
    """Domain-free by construction: this reads `is_identity` rows, so a pack
    for a category nobody has thought of yet is covered the moment it is
    installed. There is no list to add a make to."""
    store = _store_with_identity_values(
        tmp_path, [("brand", "einhell"), ("chuck_mm", "13")])
    assert identity_vocabulary(store) == {"brand": {"einhell"},
                                          "chuck_mm": {"13"}}
    store.close()


# ── composite values ─────────────────────────────────────────────────────
#
# A page often packs several facts into one cell: "Brushless / 13mm Keyless /
# Metal Gear" is a motor type, a chuck size and a gear housing. The old
# client cut those apart in JavaScript, with a branch per label — site
# knowledge in the one place that cannot be updated without shipping a
# release. `segment` is the closed replacement: pick an end of a delimited
# value, and nothing else.

SEGMENT_SPEC = {
    "id": "segments",
    "subject_kind": "product",
    "match": ["*x.invalid/*"],
    "identity": {
        "motor_type": {"labels": ["motor / chuck"], "segment": "first"},
        "chuck_type": {"labels": ["motor / chuck"], "segment": "last"},
        "voltage_v": {"labels": ["voltage"], "segment": "first"},
    },
}


def test_a_segment_rule_takes_the_named_end_of_a_delimited_value():
    got = adapt(SEGMENT_SPEC, {
        "Motor / Chuck": "Brushless / 13mm Keyless / Metal Gear",
        "Voltage": "18V / Li-ion",
    })
    assert got.identity["motor_type"] == "Brushless"
    assert got.identity["chuck_type"] == "Metal Gear"
    assert got.identity["voltage_v"] == "18V"


def test_a_segment_rule_on_a_value_with_no_delimiter_returns_the_whole_value():
    got = adapt(SEGMENT_SPEC, {"Voltage": "18V"})
    assert got.identity["voltage_v"] == "18V"


def test_first_and_last_are_the_same_segment_when_there_is_only_one():
    got = adapt(SEGMENT_SPEC, {"Motor / Chuck": "Brushless"})
    assert got.identity["motor_type"] == "Brushless"
    assert got.identity["chuck_type"] == "Brushless"


# ── labels are written by people, in their own alphabet ──────────────────
#
# Turkish "İ" casefolds to "i" plus a combining dot, so "İlan No" and
# "ilan no" are different strings to `str.casefold()` and a pack author has no
# way to tell. The same trap catches "Motor Gücü" against "motor gucu", which
# is why the cars adapter carried both spellings of every accented label — a
# hand-kept list of transliterations, and one more thing to forget.

def test_a_label_matches_whatever_accents_the_page_happened_to_use():
    got = adapt(SEGMENT_SPEC, {"VOLTAGE": "18V"})
    assert got.identity["voltage_v"] == "18V"


def test_turkish_dotted_capital_i_matches_its_plain_spelling():
    spec = {"id": "tr", "subject_kind": "product", "match": ["*"],
            "identity": {"listing": {"labels": ["ilan no"]}}}
    assert adapt(spec, {"İlan No": "123"}).identity["listing"] == "123"


def test_an_accented_label_is_ignored_by_its_plain_spelling():
    """The bug this was found by: `İlan No` and `İlan Tarihi` were listed as
    ignored and were reported as unmapped anyway, because the blocklist could
    not recognise its own entries once the page capitalised them."""
    got = adapt(_cars_spec(), {"İlan No": "1", "İlan Tarihi": "13 July 2026"},
                url="https://www.sahibinden.com/ilan/x")
    assert got.unmapped == ()


def test_accent_folding_does_not_merge_letters_turkish_treats_as_distinct():
    """"ı" is a letter, not an "i" with something taken off it. Folding it
    away would make "yakıt" and "yakit" the same label, which they are — but
    only by luck; the rule must be diacritic-stripping, not transliteration."""
    spec = {"id": "tr", "subject_kind": "product", "match": ["*"],
            "identity": {"a": {"labels": ["yakıt"]}}}
    assert "a" not in adapt(spec, {"yakit": "x"}).identity
