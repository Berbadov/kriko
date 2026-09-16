"""The agent asks, once, and does not wait.

The reader's report: *"it never asks me anything"* — and the reason that
matters is not politeness. The same commercial name is sold market to market
under different codenames, with generation and drivetrain splits that change
the failure profile completely, so a pack built on the wrong variant is worse
than no pack. It is confidently wrong.

The tension every test here is about: `CLAUDE.md`'s automation principle says
nothing in the data path waits for a human. Asking a question and blocking on
it would break that. Asking a question, stating a default, and carrying on does
not — and it is also the better product, because a run that stalls waiting for
somebody who has gone to make tea is a run that has failed.
"""

import pytest

from app import disambiguate

UNAMBIGUOUS = """
The name picks out exactly one product.

```json
{"ambiguous": false, "why": "", "established": {"maker": "Acme"},
 "questions": []}
```
"""

AMBIGUOUS = """
```json
{"ambiguous": true,
 "why": "sold under two codenames with different drivetrains",
 "established": {"maker": "Acme"},
 "questions": [
   {"id": "market", "ask": "Which market is yours sold in?", "key": "market",
    "options": ["TR", "EU"], "default": "TR",
    "because": "most listings for this name are Turkish"},
   {"id": "power", "ask": "Which power source?", "key": "power",
    "options": ["mains", "battery"], "default": "battery",
    "because": "the battery version outsells the mains one"}]}
```
"""


# ── the cheap pass ───────────────────────────────────────────────────────

def test_a_name_that_means_one_thing_asks_nothing(_=None):
    """The common case, and worth getting right.

    A question about a product with one variant wastes the reader's attention
    and teaches them to ignore the next one.
    """
    found = disambiguate.parse(UNAMBIGUOUS)
    assert found["ambiguous"] is False
    assert found["questions"] == []
    assert found["established"] == {"maker": "Acme"}


def test_an_ambiguous_name_asks_in_one_batch(_=None):
    found = disambiguate.parse(AMBIGUOUS)
    assert found["ambiguous"] is True
    assert [one["id"] for one in found["questions"]] == ["market", "power"]
    assert found["why"]


def test_no_more_than_five_questions_survive_parsing():
    """"Do not interrogate me one question at a time across the whole run."""
    many = {"ambiguous": True, "questions": [
        {"id": f"q{n}", "ask": f"Question {n}?", "default": "x"}
        for n in range(12)]}
    import json

    found = disambiguate.parse(f"```json\n{json.dumps(many)}\n```")
    assert len(found["questions"]) == disambiguate.MAX_QUESTIONS


def test_a_question_with_no_default_is_dropped():
    """A default is what makes this non-blocking. Without one it is a gate."""
    import json

    raw = {"ambiguous": True, "questions": [
        {"id": "a", "ask": "Which market?", "default": "TR"},
        {"id": "b", "ask": "Which year?"}]}
    found = disambiguate.parse(f"```json\n{json.dumps(raw)}\n```")
    assert [one["id"] for one in found["questions"]] == ["a"]


def test_a_reply_nobody_can_parse_costs_a_question_not_the_run():
    """This is the cheap step guarding the expensive one.

    An exception here would turn "we could not tell whether this was ambiguous"
    into "you get no pack", which is a far worse trade than the one it was
    added to make.
    """
    for reply in ("", "I could not decide.", "```json\n{not json at all\n```"):
        found = disambiguate.parse(reply)
        assert found["ambiguous"] is False
        assert found["questions"] == []


# ── what the run does with it ────────────────────────────────────────────

def test_an_unanswered_question_becomes_a_stated_assumption():
    """The run proceeds. What it proceeded *on* is written down."""
    found = disambiguate.parse(AMBIGUOUS)
    scope = disambiguate.scope(found, answers={})
    assert scope["identity"] == {"maker": "Acme", "market": "TR", "power": "battery"}
    assert scope["assumed"] == ["market", "power"]


def test_an_answer_replaces_the_default_and_stops_being_an_assumption():
    found = disambiguate.parse(AMBIGUOUS)
    scope = disambiguate.scope(found, answers={"power": "mains"})
    assert scope["identity"]["power"] == "mains"
    assert scope["assumed"] == ["market"], "answered keys are no longer assumed"


def test_what_the_name_itself_settled_is_never_an_assumption():
    found = disambiguate.parse(AMBIGUOUS)
    scope = disambiguate.scope(found, answers={})
    assert "maker" not in scope["assumed"]


def test_the_scope_record_is_stable_across_runs_that_assumed_the_same_things():
    """A scope that reshuffles is a scope that looks like it changed."""
    found = disambiguate.parse(AMBIGUOUS)
    assert disambiguate.scope(found) == disambiguate.scope(found)


# ── and what the reader sees ─────────────────────────────────────────────

def test_the_pack_says_what_it_was_built_for_in_plain_language():
    """The reader's own example: "built for the … , Turkish market".

    An assumed scope that is invisible is the actual bug — a pack whose
    wrongness is indistinguishable from a coverage gap.
    """
    said = disambiguate.sentence(
        disambiguate.scope(disambiguate.parse(AMBIGUOUS)))
    assert said.startswith("Built for ")
    assert "market" in said
    assert "assumed, not confirmed" in said


def test_a_fully_answered_scope_claims_nothing_it_did_not_establish():
    said = disambiguate.sentence(disambiguate.scope(
        disambiguate.parse(AMBIGUOUS), answers={"market": "EU", "power": "mains"}))
    assert "assumed" not in said


def test_nothing_established_says_nothing_rather_than_an_empty_sentence():
    assert disambiguate.sentence({"identity": {}, "assumed": []}) == ""


def test_the_authoring_brief_carries_the_scope_to_the_agent():
    """An agent that does not know which variant it is writing about averages
    several into one, and a pack that averages two failure profiles describes
    neither."""
    from app.packauthor import brief

    scope = disambiguate.scope(disambiguate.parse(AMBIGUOUS))
    with_scope = brief("power tools", scope=scope)
    assert "The scope of this pack" in with_scope
    assert "Built for " in with_scope
    # And without one it reads exactly as it did before this existed.
    assert "The scope of this pack" not in brief("power tools")


def test_the_identification_brief_never_invents_identity_keys():
    """A question whose answer maps to a key no pack declares is a fact with
    nowhere to go — so the packs' own vocabulary is passed in, never listed."""
    text = disambiguate.brief("a thing", keys="* `tools` / `product`: `brand`")
    assert "`brand`" in text
    assert "at most 5 questions" in text.lower()


@pytest.mark.parametrize("signal", disambiguate.SIGNALS)
def test_every_ambiguity_signal_reaches_the_agent(signal):
    assert signal in disambiguate.brief("a thing")
