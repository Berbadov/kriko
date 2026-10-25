"""The plan a research turn owes, as pure functions: no model, no network."""

import pytest

from app.providers import agentplan, local_search_plan


@pytest.mark.parametrize(("question", "expected"), [
    ("Is the Galaxy Buds2 Pro worth 90 dollars?", ("galaxy", "buds2", "pro")),
    ("what goes wrong with the 2019 Honda Civic?", ("honda", "civic")),
    ("Galaxy Buds2 Pro 90 dolara değer mi?", ("galaxy", "buds2", "pro")),
    # A capital in the middle of a sentence is a name even where the word is
    # also a question word elsewhere (Turkish "mi"); a bare number never is.
    ("Is the Mi 11 any good", ("mi",)),
    ("what should I look at", ()),
    ("", ()),
])
def test_identity_terms_keep_the_names_and_codes_of_the_question(question, expected):
    assert agentplan.identity_terms(question) == expected


def test_identity_terms_are_bounded_and_deduplicated():
    question = "Compare Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Alpha"
    terms = agentplan.identity_terms(question)
    assert len(terms) == agentplan.MAX_IDENTITY_TERMS
    assert len(set(terms)) == len(terms)


def test_a_model_code_must_appear_whatever_spacing_the_page_uses():
    identity = ("galaxy", "buds2", "pro")
    assert agentplan.mentions(identity, "Samsung Galaxy Buds 2 Pro review") is True
    assert agentplan.mentions(identity, "Galaxy Buds2 Pro: one year later") is True
    assert agentplan.mentions(identity, "Galaxy Buds Live teardown") is False


def test_plain_names_must_mostly_appear_as_whole_words():
    identity = ("honda", "civic")
    assert agentplan.mentions(identity, "2019 Honda Civic owners report") is True
    assert agentplan.mentions(identity, "Honda Accord owners report") is False
    # "pro" inside "problem" is not the word.
    assert agentplan.mentions(("widget", "pro"), "A widget problem thread") is False


def test_unknown_identity_is_not_a_verdict():
    assert agentplan.mentions((), "anything at all") is None


@pytest.mark.parametrize(("question", "kinds"), [
    ("What are the specs of the Widget X100?", ("manufacturer",)),
    ("Any known problems or recall notices for the Widget X100?", ("forums", "recalls")),
    ("Is the Widget X100 worth buying?", ()),
])
def test_the_plan_reads_the_kinds_the_question_names(question, kinds):
    assert agentplan.make_plan(question, ceiling=8).kinds == kinds


def test_a_lookup_is_worth_less_than_a_hunt_for_failures():
    lookup = "What are the specs of the Widget X100?"
    hunt = "Any known problems or recall notices for the Widget X100?"
    unnamed = "Is the Widget X100 worth buying?"
    assert agentplan.make_plan(lookup, ceiling=8).calls == agentplan.LOOKUP_CALLS
    assert agentplan.make_plan(hunt, ceiling=8).calls == 8
    # A question that names no kind fails open to the dial untouched.
    assert agentplan.make_plan(unnamed, ceiling=8).calls == 8


def test_the_plan_never_exceeds_the_dial():
    assert agentplan.make_plan("What are the specs of the Widget X100?", ceiling=3).calls == 3
    assert agentplan.make_plan("anything", ceiling=0).calls == 0


def test_coverage_hint_names_only_what_is_still_owed_and_affordable():
    plan = agentplan.make_plan("Any known problems or recall notices for the Widget X100?",
                               ceiling=8)
    hint = agentplan.coverage_hint(plan, {"forums"}, calls_left=3)
    assert [row["kind"] for row in hint["still_asked"]] == ["recalls"]
    assert hint["still_asked"][0]["word"] == local_search_plan.kind_marker("recalls")
    assert hint["retrievals_left"] == 3
    assert agentplan.coverage_hint(plan, {"forums"}, calls_left=0) == {}
    assert agentplan.coverage_hint(plan, {"forums", "recalls"}, calls_left=3) == {}


def test_every_kind_of_source_has_a_freshness_and_notices_go_stale_first():
    assert set(agentplan.FRESHNESS_SECONDS) == set(local_search_plan.SOURCE_KINDS)
    assert (agentplan.search_ttl("recalls", 900)
            < agentplan.search_ttl("forums", 900)
            < agentplan.search_ttl("manufacturer", 900))
    assert agentplan.search_ttl("", 900) == 900


def test_records_merge_by_adding_and_a_covered_kind_stops_being_missing():
    first = agentplan.build_record(
        searches=2, kinds=["forums"], missing=["recalls"], pages=3, unreadable=1,
        cached=0, retrieved=4, on_product=2, off_product=1)
    second = agentplan.build_record(
        searches=1, kinds=["recalls"], missing=[], pages=1, unreadable=0,
        cached=1, retrieved=1)
    merged = agentplan.merge_records(first, second)
    assert merged["searches"] == 3
    assert merged["pages"] == 4
    assert merged["unreadable"] == 1
    assert merged["cached"] == 1
    assert merged["retrieved"] == 5
    assert merged["kinds"] == ["forums", "recalls"]
    assert merged["missing"] == []
    assert merged["on_product"] == 2 and merged["off_product"] == 1


def test_merging_nothing_stays_nothing_and_junk_is_ignored():
    assert agentplan.merge_records(None, None) == {}
    assert agentplan.merge_records({}, {"searches": True, "pages": -3}) == {
        "searches": 0, "pages": 0, "unreadable": 0, "cached": 0, "retrieved": 0,
        "kinds": [], "missing": [],
    }


def test_the_record_line_says_what_the_screen_will():
    record = agentplan.build_record(
        searches=3, kinds=["forums", "reviews"], missing=["recalls"], pages=5,
        unreadable=1, cached=0, retrieved=4, on_product=4, off_product=1)
    line = agentplan.record_line(record)
    assert line.startswith("record: 3 search(es) · 5 page(s) read")
    assert "1 unreadable" in line
    assert "1 not about this product" in line
    assert "kinds: forums, reviews" in line
    assert "not searched: recalls" in line
    assert agentplan.record_line({}) == ""
