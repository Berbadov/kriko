"""B148: the quick look keeps only what names its page, and never waits in line."""

import json
import threading

from app import quicklook
from app.web import jobs


def _fenced(payload) -> str:
    return "Reading done.\n```json\n" + json.dumps(payload) + "\n```"


def test_a_risk_without_a_page_and_a_quote_is_dropped():
    found = quicklook.parse(_fenced({"assumed": "the 2.0 diesel", "risks": [
        {"title": "Injector seals", "why": "They leak.", "check": "Ask for invoices",
         "severity": "HIGH", "url": "https://www.example.org/x", "quote": "seals leak"},
        {"title": "No page", "why": "x", "quote": "y"},
        {"title": "No quote", "url": "https://example.org/y"},
        {"title": "Not a web page", "url": "file:///etc/passwd", "quote": "z"},
        "not an object",
    ]}))
    assert found["assumed"] == "the 2.0 diesel"
    assert found["dropped"] == 4
    [card] = found["risks"]
    assert card["title"] == "Injector seals"
    assert card["severity"] == "high"
    assert card["domain"] == "example.org"
    assert card["advice"] == "Ask for invoices"
    assert card["sources"] == [
        {"url": "https://www.example.org/x", "domain": "example.org", "quote": "seals leak"}]
    # Not a stored claim: no verdict button may attach to it.
    assert "claim_id" not in card


def test_an_unreadable_reply_is_an_honest_nothing():
    assert quicklook.parse("I could not find anything.") == {
        "assumed": "", "product": "", "category": "", "pack": "", "pack_identity": {},
        "price": {}, "specs": [], "risks": [],
        "dropped": 0}


def test_current_listing_price_takes_priority_over_an_owners_historical_payment():
    found = quicklook.parse(_fenced({"risks": [], "specs": [], "price": {
        "amount": "20,000", "currency": "TRY", "seller": "Old seller",
        "url": "https://owners.example/review", "quote": "I paid 20,000 TRY last year.",
    }}), {"https://owners.example/review": "I paid 20,000 TRY last year."},
        page={"facts": {"price": "18,500 TRY", "seller": "Current shop"}})
    assert found["price"]["amount"] == 18500
    assert found["price"]["seller"] == "Current shop"
    assert found["price"]["source"] == "listing"


def test_the_answer_names_the_kind_of_product_and_a_pack_id_in_one_short_line():
    found = quicklook.parse(_fenced({
        "assumed": "x", "category": "  wireless\n earbuds ", "pack": " Audio.Earbuds ",
        "risks": []}))
    assert found["category"] == "wireless earbuds"
    assert found["pack"] == "audio.earbuds"
    long = quicklook.parse(_fenced({"category": "word " * 60}))
    assert len(long["category"]) <= 80


def test_a_quote_the_plane_saw_is_marked_grounded_and_a_cli_quote_is_not():
    reply = _fenced({"risks": [{"title": "Gear wear", "url": "https://e.org/a",
                                "quote": "the gears wear"}]})
    seen = quicklook.parse(reply, {"https://e.org/a": "Notes: the  gears wear fast."})
    assert seen["risks"][0]["sources"][0]["grounded"] is True
    assert seen["risks"][0]["sources"][0]["quote"] in "Notes: the  gears wear fast."
    unseen = quicklook.parse(reply)
    assert "grounded" not in unseen["risks"][0]["sources"][0]
    assert quicklook.parse(reply, {"https://e.org/a": "nothing here"})["dropped"] == 1


def test_at_most_max_risks_are_kept():
    many = [{"title": f"r{i}", "url": "https://e.org", "quote": "q"} for i in range(20)]
    assert len(quicklook.parse(_fenced({"risks": many}))["risks"]) == quicklook.MAX_RISKS


def test_the_brief_carries_the_product_and_the_packs_bar():
    text = quicklook.brief("Bosch GSR 18V-55", "Only variant-specific failures.")
    assert text.startswith("# Quick look")
    assert "Bosch GSR 18V-55" in text
    assert "Only variant-specific failures." in text
    # Nothing is installed: there is no "where it belongs" question to ask.
    assert "Where it belongs" not in text


def test_compatibility_guidance_requires_exact_constraints_for_pc_and_vehicle_parts():
    text = quicklook.brief("A motherboard and a replacement engine sensor")
    folded = text.casefold()
    for term in ("socket", "chipset", "bios", "memory generation", "form factor",
                 "power connectors", "clearance", "model year", "market",
                 "engine code", "transmission", "part number"):
        assert term in folded
    assert "compatibility is unconfirmed" in folded
    assert "broad fitment list is not enough" in folded


def test_quicklook_report_does_not_set_a_target_finding_count():
    text = quicklook.brief("A product with varying complexity")
    assert "There is no target number of lines" in text
    assert "fits the product's complexity and the strength of the evidence" in text


def test_market_region_guidance_is_optional_and_applies_to_quicklook():
    automatic = quicklook.brief("A product")
    regional = quicklook.brief("A product", market_region="TR")
    assert "preferred market" not in automatic
    assert "reader's preferred market is Türkiye (TR)" in regional
    assert "market applicability" in regional


def test_the_brief_lists_the_installed_packs_when_there_are_some():
    text = quicklook.brief("Scyrox V6", "", None,
                           "* `gaming.mice`, Gaming mice (holds Scyrox V8): mice")
    assert "## Where it belongs" in text
    assert "`gaming.mice`" in text
    assert "leave `pack` empty" in text
    assert '"pack":' in text and '"category":' in text


def test_a_quick_kind_is_not_queued_behind_a_long_job(tmp_path):
    holding = threading.Event()
    release = threading.Event()
    quick_done = threading.Event()

    def long_job(settings, params, progress):
        holding.set()
        assert release.wait(10)
        return {}

    def quick(settings, params, progress):
        quick_done.set()
        return {}

    settings = type("S", (), {"app_state_path": tmp_path / "app.sqlite"})()
    runner = jobs.JobRunner(settings, {"pack_author": long_job, "quick_look": quick})
    try:
        runner.submit("pack_author", {})
        assert holding.wait(10)
        runner.submit("quick_look", {})
        assert quick_done.wait(10), "the quick look waited for the long job"
    finally:
        release.set()
        runner.shutdown(wait=True)


def test_a_reply_cut_off_at_its_budget_keeps_the_items_it_finished():
    """A CPU model that ran out of tokens mid-risk: the finished risk is
    kept, by the same checks as any other, and the cut one is not."""
    page = "The pump seal leaks after the first winter."
    reply = (
        '```json\n{"assumed": "x", "category": "pumps", "pack": "", "specs": [],\n'
        ' "risks": [{"title": "Seal leak", "why": "w", "check": "c",'
        ' "severity": "high", "url": "https://a.test/1",'
        ' "quote": "The pump seal leaks after the first winter."},\n'
        '  {"title": "Second", "why": "this one was cut off at the bud')
    out = quicklook.parse(reply, {"https://a.test/1": page})
    assert [one["title"] for one in out["risks"]] == ["Seal leak"]


def test_a_reply_with_no_object_closes_to_nothing():
    assert quicklook.closed("no json here") is None
    assert quicklook.closed('{"risks": [') is None


def test_complete_answer_payload_requires_both_result_arrays():
    assert quicklook.answer_payload('{"risks": [], "specs": []}') == {
        "risks": [], "specs": []}
    assert quicklook.answer_payload('{"risks": []}') is None
    assert quicklook.answer_payload('not JSON') is None


def test_answer_payload_can_recover_a_closed_complete_object():
    answer = '{"risks": [], "specs": [], "category": "television"} trailing output'
    assert quicklook.answer_payload(answer)["category"] == "television"


def test_a_trailing_comma_does_not_cost_the_reply():
    reply = ('{"specs": [{"name": "a", "value": "1", "url": "https://a.test/1"},],'
             ' "risks": [')
    assert quicklook.closed(reply)["specs"][0]["name"] == "a"


def test_no_supported_issues_is_bounded_by_completed_coverage():
    coverage = {
        "status": "no_supported_findings", "pages_read": 2,
        "pages_relevant": 1, "pages_extracted": 1,
    }
    message = quicklook.outcome(
        '{"risks": [], "specs": []}', {"risks": [], "specs": []},
        coverage=coverage)
    assert "no known issues found in 1 relevant page(s) checked" in message
    assert "1 completed check(s)" in message

    for gap in ("pages_timed_out", "pages_unreadable", "errors", "search_errors"):
        incomplete = {**coverage, gap: 1 if gap.startswith("pages_") else ["failed"]}
        assert not quicklook.has_complete_negative_coverage(incomplete)
        assert "incomplete" in quicklook.outcome(
            '{"risks": [], "specs": []}', {"risks": [], "specs": []},
            coverage=incomplete)


def test_a_harness_answer_pass_can_support_a_bounded_negative_result():
    coverage = {"status": "no_supported_findings", "pages_read": 3,
                "pages_relevant": 2, "pages_extracted": 0, "answer_passes": 1}
    assert quicklook.has_complete_negative_coverage(coverage)
    assert "2 relevant page(s) checked" in quicklook.outcome(
        '{"risks": [], "specs": []}', {"risks": [], "specs": []},
        coverage=coverage)


def test_every_brief_asks_for_the_listings_language_and_untranslated_quotes():
    """The same listing answered in two languages when the sources' language
    decided it. The rule rides in both shapes of the brief and names no language."""
    for compact in (False, True):
        text = quicklook.brief("Widget 5000", compact=compact)
        assert quicklook.LANGUAGE_RULE in text
    assert "Turk" not in quicklook.LANGUAGE_RULE
    assert "never translate a quote" in quicklook.LANGUAGE_RULE


def test_both_briefs_say_a_shop_is_the_seller_speaking_and_its_customers_are_not():
    for compact in (False, True):
        text = quicklook.brief("Widget 5000", compact=compact)
        assert quicklook.SHOP_RULE in text
    assert "customers wrote" in quicklook.SHOP_RULE
    assert "\"original\"" in quicklook.SHOP_RULE


def _found(*urls):
    return {"specs": [{"name": "Brand", "value": "Acme", "url": url, "domain": "x", "quote": "q"}
                      for url in urls], "risks": [], "dropped": 0}


def test_a_spec_that_only_repeats_the_listing_page_is_left_out():
    listing = "https://www.shop.example/p/acme-widget-5000?utm=1#reviews"
    found = _found("https://shop.example/p/acme-widget-5000/", "https://review.example/widget")
    kept = quicklook.without_listing_echo(found, listing)
    assert [one["url"] for one in kept["specs"]] == ["https://review.example/widget"]
    assert kept["echoed"] == 1


def test_a_spec_from_another_page_of_the_same_shop_is_kept():
    found = _found("https://shop.example/p/another-widget")
    assert quicklook.without_listing_echo(found, "https://shop.example/p/acme-widget-5000") is found


def test_with_no_listing_address_nothing_is_left_out():
    found = _found("https://shop.example/p/acme-widget-5000")
    assert quicklook.without_listing_echo(found, "") is found
