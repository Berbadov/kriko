"""A brief carries what its answer needs, and not the whole store.

The reader's requirement: *"They must see relevant context"*. The failure mode
is not an empty brief — it is a brief so full that the question is a rounding
error in it. Measured before this work, on a check of eight risks:

* a single follow-up on one listing was handed **37,229 characters**, of which
  10,523 were the stored record (coverage counts, the research diagnostic, six
  specifications with quotes, every listing fact, five page excerpts) and the
  rest up to six earlier questions with *their* whole answers — for a reply
  capped at seventy words;
* a Quick Look on a twelve-catalog install was handed the whole installed
  catalogue, +3,775 characters, for a value that is a tie-breaking hint
  (`categorizer.deterministic` decides from the whole set by itself).

What an answer needs is the product's identity, the risks recorded for it with
the pages they came from, and the question. These tests are that sentence.
"""

import json

from app import categorizer, followup
from app.web import tasks


def _profile(pack_id, name, *, kinds=(), attributes=()):
    return {
        "pack_id": pack_id, "name": name, "enabled": True, "editable": False, "slug": "",
        "definition": {
            "kinds": [{"id": value.casefold().replace(" ", "_"), "label": value}
                      for value in kinds],
            "identity_keys": [],
            "attributes": [{"id": value.casefold().replace(" ", "_"), "label": value}
                           for value in attributes],
            "examples": [],
        },
        "terms": [name, *kinds, *attributes],
    }


def _stored(**overrides) -> dict:
    response = {
        "category": "cordless drill",
        "assumed": "the 55 model",
        "diagnostic": {"message": "3 of 7 pages were readable."},
        "coverage": {"status": "partial", "pages_read": 7, "pages_relevant": 3,
                     "pages_extracted": 1, "publishers_read": 4},
        "identity": {"brand": "Bosch", "model": "GSR 18V-55"},
        "listing": {"url": "https://shop.example/d/1",
                    "facts": {f"fact {index}": "value " * 6 for index in range(24)},
                    "description": "Seller description " * 40},
        "claims": [{"title": f"Risk {index}", "body": "It fails. " * 20,
                    "advice": "Check it.", "severity": "high",
                    "sources": [{"url": f"https://forum.example/{index}",
                                 "quote": "A quote from the page. " * 8}]}
                   for index in range(8)],
        "specs": [{"name": f"Spec {index}", "value": "1.5 kg",
                   "url": "https://a.example/x", "quote": "1.5 kg"} for index in range(6)],
        "context": {f"k{index}": "v" for index in range(8)},
        "evidence_pages": [{"url": f"https://p.example/{index}", "excerpt": "x" * 700}
                           for index in range(5)],
    }
    response.update(overrides)
    return {"label": "Bosch GSR 18V-55", "response": response}


def _previous(count: int) -> list[dict]:
    return [{"state": "succeeded",
             "params": {"question": "Is it quiet? " * 20},
             "result": {"answer": f"Answer number {index}. " * 100}}
            for index in range(count)]


def test_a_follow_up_brief_carries_the_identity_the_risks_and_their_pages():
    text = tasks._follow_up_context(_stored(), "Is the seller reliable?", _previous(0))

    assert "cordless drill" in text
    assert "the 55 model" in text
    assert "brand: Bosch" in text and "model: GSR 18V-55" in text
    assert "Listing page: https://shop.example/d/1" in text
    assert "Risk 0" in text and "Risk 7" in text
    assert "source: https://forum.example/0" in text
    assert "A quote from the page." in text
    assert "Research coverage: partial." in text


def test_a_follow_up_brief_leaves_out_what_the_answer_does_not_use():
    text = tasks._follow_up_context(_stored(), "Is the seller reliable?", _previous(0))

    assert "3 of 7 pages were readable" not in text, "the diagnostic is not evidence"
    assert "pages_extracted" not in text and "publisher bucket" not in text
    assert "Spec 0" not in text, "specifications are a different question's material"
    assert "Page read:" not in text, "whole page excerpts are not a brief"
    assert "fact 23" not in text, "listing facts the question did not ask about"
    assert "Seller description" not in text


def test_a_follow_up_brief_grows_bounded_with_the_number_of_earlier_questions():
    asked_many = tasks._follow_up_context(_stored(), "Is it quiet?", _previous(6))
    asked_endless = tasks._follow_up_context(_stored(), "Is it quiet?", _previous(20))

    # The last three exchanges are conversation; the fourth-oldest is a scroll
    # away in the panel and not something the answer may rest on anyway.
    assert asked_many.count("Agent reply:") == tasks.FOLLOW_UP_HISTORY
    assert len(asked_endless) == len(asked_many), "twenty questions is not a longer brief"
    assert "Answer number 0" not in asked_many, "the oldest exchange is the one dropped"
    assert "Answer number 5" in asked_many, "the newest exchange is the one kept"
    assert "Answer number 19" in asked_endless
    # And each kept answer is clipped, so no single one can dominate it.
    record = len("\n".join(tasks._follow_up_lines(_stored(), "Is it quiet?")))
    assert len(asked_many) < record + tasks.FOLLOW_UP_HISTORY * (
        tasks.FOLLOW_UP_HISTORY_CHARS + 400)


def test_the_risk_the_question_names_survives_the_count_bound():
    """A brief cut to a count must cut the claims the question is not about."""
    stored = _stored(claims=[
        {"title": f"Risk {index}", "body": "It fails.", "severity": "low", "sources": []}
        for index in range(20)])
    stored["response"]["claims"][19]["title"] = "The seller refuses refunds"

    text = tasks._follow_up_context(stored, "does the seller refuse refunds?", [])

    assert "The seller refuses refunds" in text
    assert "further recorded risk(s)" in text, "a cut brief must count what it cut"


def test_an_empty_record_still_says_so_rather_than_looking_like_no_risk():
    text = tasks._follow_up_lines(_stored(claims=[], specs=[]), "anything")

    assert "Known risks: none recorded." in text


# ── the Quick Look's catalogue ──────────────────────────────────────────────


def test_a_quick_look_is_shown_the_catalogs_that_could_take_the_product():
    profiles = [_profile(f"cat.{index:02d}", f"Category {index:02d} appliances",
                         kinds=(f"kind {index:02d}",))
                for index in range(20)]

    block, note = tasks._catalogue_block("Category 07 product", None, profiles)

    shown = [one["pack_id"] for one in
             categorizer.shortlist("Category 07 product", None, profiles)]
    assert 0 < len(shown) <= categorizer.SHORTLIST
    assert len(shown) < len(profiles)
    assert all(f"`{pack_id}`" in block for pack_id in shown)
    assert note == ""


def test_the_pack_the_reader_named_is_always_on_the_list():
    profiles = [_profile(f"cat.{index:02d}", f"Category {index:02d} appliances")
                for index in range(20)]

    shown = categorizer.shortlist("something else entirely", None, profiles,
                                  limit=3, pinned="cat.17")

    assert shown[0]["pack_id"] == "cat.17"


def test_a_catalogue_too_large_for_one_prompt_is_shrunk_not_replaced():
    """A smaller honest list beats a sentence that says there is no list."""
    small = _profile("cat.01", "Small appliances", kinds=("kettle",))
    huge = _profile("cat.02", "Huge appliances", kinds=("kettle",))
    huge["definition"]["attributes"] = [{"id": "data", "label": "long" * 40_000}]

    block, note = tasks._catalogue_block("kettle", None, [small, huge])

    assert "`cat.01`" in block and "long" * 100 not in block
    assert note == ""


def test_a_catalogue_no_subset_of_which_fits_says_so_and_names_the_way_out():
    huge = _profile("cat.02", "Huge appliances", kinds=("kettle",))
    huge["definition"]["attributes"] = [{"id": "data", "label": "long" * 40_000}]

    block, note = tasks._catalogue_block("kettle", None, [huge])

    assert block == ""
    assert "too large for one prompt" in note and "by hand" in note


def test_the_follow_up_wording_lives_in_one_place_for_both_panels():
    """Context is assembled by the job; the *wording* lives in `app/followup.py`,
    so the listing panel and the quick look's panel cannot drift apart."""
    listing = followup.web_brief("Is it quiet?", product="A", context="c")
    quick = followup.web_brief("Is it quiet?", product="A", context="c")

    assert listing == quick
    assert followup.RULES in listing
    assert json.dumps  # the answers are JSON-shaped, so the briefs are too
