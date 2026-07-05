"""Deterministic model-name grounding — bypasses gate_variant's LLM call when
the car model+generation is named directly in the evidence, per gate_variant's
own prompt criterion #1 ("the evidence text or source URL mentions the car
model/generation name").

Regression coverage for project-memory finding: body-domain claims that named
the model directly were still `held` by gate_variant (ministral-8b) for no
clear reason — same class of unreliability as the engine-code case fixed by
_shares_code_token (test_variant_code_grounding.py).
"""

from knowledge.promote import _model_mention_variants, _shares_model_mention

MEGANE4_DESCS = [
    "Renault Megane IV H5H petrol 1332cc 115–140hp automatic (edc) (2016–present)",
    "Renault Megane IV K9K diesel 1461cc 90–110hp manual (manual) (2016–present)",
]

CLIO5_DESCS = [
    "Renault Clio V H5H petrol 1332cc 130–130hp manual (manual) (2019–present)",
]

GOLF7_DESCS = [
    "Volkswagen Golf VII EA211 petrol 1395cc 125–125hp manual (manual) (2013–2020)",
]


def test_arabic_digit_mention_grounds():
    assert _shares_model_mention("Sunroof drain clogging common on Megane 4 models", MEGANE4_DESCS)


def test_roman_numeral_mention_grounds():
    assert _shares_model_mention("Known issue on the Megane IV since launch", MEGANE4_DESCS)


def test_hyphenated_mention_grounds():
    assert _shares_model_mention("megane-4 boot latch corrosion reported widely", MEGANE4_DESCS)


def test_concatenated_mention_grounds():
    assert _shares_model_mention("megane4 rear light seal water ingress", MEGANE4_DESCS)


def test_turkish_ordinal_word_mention_grounds():
    assert _shares_model_mention("Megane Dört modellerinde sık görülen bir arıza", MEGANE4_DESCS)


def test_accented_mention_grounds():
    assert _shares_model_mention("Défaut connu sur la Mégane IV depuis le lancement", MEGANE4_DESCS)


def test_different_model_does_not_ground():
    assert not _shares_model_mention("Common fault on the Clio 5 dashboard", MEGANE4_DESCS)


def test_same_model_different_generation_does_not_ground():
    # Clio III content should not ground against Clio V variants.
    assert not _shares_model_mention("Well known issue on the Clio 3", CLIO5_DESCS)


def test_no_mention_falls_through():
    assert not _shares_model_mention("Generic turbo whine reported by several owners", GOLF7_DESCS)


def test_variants_are_generated_not_hardcoded():
    variants = _model_mention_variants("Megane", "IV")
    assert {"megane 4", "megane iv", "megane dort", "megane4", "megane-4"} <= variants
