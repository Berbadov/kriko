"""A listing that says "original" has not shown that the part is.

A reader asked for an original part from a trusted seller. The agent counted the
word "orjinal" in listing titles as the originality check, and told them from
memory that a maker's own local distributor was not the maker's brand. Every
brief the chat sends a model now carries the rule: the seller's words are the
seller's claim, and what checks originality is something else.
"""

from app import chat


def _briefs():
    history: list[dict] = []
    need = {"product": "oil filter"}
    rounds: list[dict] = []
    return {
        "plan": chat.plan_brief("an original oil filter", history),
        "refine": chat.refine_brief("an original oil filter", history, rounds),
        "answer": chat.answer_brief("an original oil filter", history, need, rounds, detailed=False),
        "chat": chat.chat_brief("is this seller trustworthy?", history),
        "web": chat.web_answer_brief("an original oil filter", history, [], ""),
    }


def test_every_brief_says_a_listings_own_word_is_not_a_check():
    for name, text in _briefs().items():
        assert chat.TRUST_RULE in text, name


def test_the_rule_names_what_does_check_it_and_forbids_asserting_a_brand_from_memory():
    rule = chat.TRUST_RULE
    assert "has not passed an originality check" in rule
    assert "maker's own number" in rule
    assert "authorised or official" in rule
    assert "not to assert from memory" in rule


def test_a_trust_question_is_planned_around_the_seller_and_the_makers_dealers():
    plan = chat.plan_brief("is this seller trustworthy?", [])
    assert "search for the seller by its own name" in plan
