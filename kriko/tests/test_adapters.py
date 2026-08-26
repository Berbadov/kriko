"""Scraped page -> query, using rules a pack supplies.

Two things are being defended here.

**Site knowledge belongs to a pack.** The old `/analyze` knew about Sahibinden;
this knows about adapters, and the cars pack knows about Sahibinden. A new
listing site is a JSON file.

**A wrong number is worse than a missing one.** Scraped values lie in a
specific way — "1.461 cm3" and "148.000 km" carry the same digits and different
magnitudes — so range bounds decide what is believable, and anything outside
them is dropped rather than trusted. A missing value fails open and says so; a
confidently wrong one silently answers about a different car.
"""

import json

from kriko.adapters import adapt, adapter_for, load_adapters

SPEC = {
    "id": "demo",
    "subject_kind": "product",
    "match": ["*example.com/ilan/*"],
    "identity": {
        "make": {"labels": ["marka", "make"]},
        "displacement_cc": {"labels": ["motor hacmi"], "parse": "int_range",
                            "min": 500, "max": 8000},
        "build_year": {"labels": ["yıl", "year"], "parse": "int_range",
                       "min": 1980, "max": 2035},
    },
    "context": {
        "usage_km": {"labels": ["km", "kilometre"], "parse": "int_range",
                     "min": 0, "max": 2_000_000},
        "free_text": {"from": "description"},
    },
    "derive": [{"key": "age_years", "op": "years_since", "from": "build_year"}],
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
    got = adapt(SPEC, {"Marka:": "Renault", "Motor Hacmi (cm3)": "1461"})
    assert got.identity["make"] == "Renault"
    assert got.identity["displacement_cc"] == 1461


def test_range_bounds_disambiguate_identical_digit_patterns():
    """The crux. Both strings are dot-separated digits; the bounds decide."""
    got = adapt(SPEC, {"Motor Hacmi": "1.461 cm3", "KM": "148.000"})
    assert got.identity["displacement_cc"] == 1461
    assert got.context["usage_km"] == 148_000


def test_a_value_outside_its_range_is_dropped_rather_than_believed():
    """Fail open. A missing mileage downranks a claim and says why; a mileage of
    nine million would gate every interval claim wrongly and say nothing."""
    got = adapt(SPEC, {"KM": "9.000.000.000"})
    assert "usage_km" not in got.context


def test_a_field_the_page_does_not_have_is_simply_absent():
    got = adapt(SPEC, {"Marka": "Renault"})
    assert got.identity == {"make": "Renault"}
    assert "usage_km" not in got.context


def test_text_fields_come_from_named_sources_not_labels():
    got = adapt(SPEC, {}, description="Tek elden, bakımlı")
    assert got.context["free_text"] == "Tek elden, bakımlı"


def test_derived_values_are_arithmetic_not_scraping():
    from datetime import date
    got = adapt(SPEC, {"Yıl": "2018"})
    assert got.context["age_years"] == date.today().year - 2018


def test_derivation_is_skipped_when_its_input_is_missing():
    assert "age_years" not in adapt(SPEC, {"Marka": "Renault"}).context


# ── coverage signal ──────────────────────────────────────────────────────

def test_labels_with_no_rule_are_reported_not_silently_dropped():
    """A site adding a useful field should be discoverable.

    Silently ignoring unknown labels is how an adapter rots: the page starts
    carrying something worth reading and nobody finds out for a year.
    """
    got = adapt(SPEC, {"Marka": "Renault", "Kimden": "Sahibinden",
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
    """The shape extension_ui/content.js actually produces today."""
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
