"""A catalogue adds to a chat turn only what the turn is about.

`product_match` widens to single words when the whole phrase finds little, so a
phone question used to bring back a boiler and a car that shared a short word
with it, as cards and as records in the prompt. The gate keeps a row only when
a name its own catalogue records for it appears in the turn.
"""

from app import chat, exactfind

BOILER = {"label": "Acme Thermo Premix 30 kW", "identity": {"brand": "acme", "series": "thermo premix"}}
CAR = {"label": "Zeta Hatch 1.4 (2014)", "identity": {"brand": "zeta", "series": "hatch", "engine": "1.4t"}}
NAMELESS = {"label": "Quiet Fan Deluxe", "identity": {}}


def kept(*texts):
    out = chat.relevant_catalogue({"rows": [BOILER, CAR, NAMELESS], "note": ""}, *texts)
    return [row["label"] for row in out["rows"]]


def test_a_question_about_another_product_keeps_no_catalogue_row():
    assert kept("Nothing Phone 4a Pro 20.000 TL bütçe varyant", "pro budget phone") == []


def test_a_product_named_in_the_question_or_the_pages_is_kept():
    assert kept("Zeta hatch kış lastiği") == ["Zeta Hatch 1.4 (2014)"]
    assert kept("which one", "ACME Thermo Premix review") == ["Acme Thermo Premix 30 kW"]


def test_a_row_without_identity_is_judged_by_its_label():
    assert kept("is the quiet fan any good") == ["Quiet Fan Deluxe"]
    assert kept("a quiet room") == []


def test_no_catalogue_stays_none():
    assert chat.relevant_catalogue(None, "anything") is None


def test_research_is_a_mode_but_not_a_buying_turn():
    assert chat.mode_of("tell me about it", "research") == "research"
    assert chat.mode_of("tell me about it", "find") == "find"
    assert "research" in chat.INFO_MODES and "find" not in chat.INFO_MODES
    assert exactfind.mode_query("Acme X1", "research").startswith("Acme X1 ")


def test_a_product_only_answer_must_pick_and_link():
    rules = " ".join(chat.PRODUCT_ONLY_RULES)
    assert "none could be verified" not in rules
    assert "[name](https://full-url)" in rules
