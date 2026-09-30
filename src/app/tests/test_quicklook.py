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
        "assumed": "", "category": "", "pack": "", "risks": [], "dropped": 0}


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
