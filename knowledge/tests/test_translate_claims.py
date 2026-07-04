"""_needs_translation heuristic — regression coverage for a real false-positive
that caused data loss: a title with a legitimate original-language technical
gloss in parentheses ("...2.0 TDI PD (Pump-Düse) engines rated at 170
horsepower") was already correct English, but got re-flagged on the umlaut in
"Düse" and the LLM "translation" ballooned it into a 490-char paragraph
duplicating the rationale. Parenthetical asides must be stripped before the
non-English check.
"""

from knowledge.translate_claims import _needs_translation


def test_parenthetical_technical_gloss_not_flagged():
    claim = {
        "title": "Frequent and recurring fuel injector failures in 2.0 TDI PD "
        "(Pump-Düse) engines rated at 170 horsepower (and some 140 horsepower models)",
        "rationale": "irrelevant",
        "inspection_advice": "irrelevant",
    }
    assert not _needs_translation(claim)


def test_turkish_gloss_in_parens_not_flagged():
    claim = {
        "title": "Chronic catalytic converter clogging causing loss of power",
        "rationale": "irrelevant",
        "inspection_advice": "irrelevant",
    }
    assert not _needs_translation(claim)


def test_wholesale_foreign_title_still_flagged():
    claim = {
        "title": "IBS (Akü Sensörü) Arızalanması",
        "rationale": "irrelevant",
        "inspection_advice": "irrelevant",
    }
    assert _needs_translation(claim)


def test_german_title_still_flagged():
    claim = {
        "title": "Kupplungsüberhitzung (EDC Doppelkupplungsgetriebe)",
        "rationale": "irrelevant",
        "inspection_advice": "irrelevant",
    }
    assert _needs_translation(claim)


def test_plain_english_title_not_flagged():
    claim = {
        "title": "Timing chain stretch on 1.3 TCe engines",
        "rationale": "irrelevant",
        "inspection_advice": "irrelevant",
    }
    assert not _needs_translation(claim)
