"""Deterministic code-token grounding — bypasses gate_variant's LLM call when
the engine/transmission code appears verbatim in both evidence and variant
description.

Regression test for a live bug found on Golf 7 EA211: gate_variant
(ministral-8b) rejected "EA211 1.4 TSI" evidence against a "...EA211 petrol
1395cc..." variant description on an invented "non-TSI" distinction, even
though the exact code was present in both — repeatably, not a one-off flake.
That silently stranded genuine claims as `held` ("no variant grounded").
"""

from knowledge.promote import _code_tokens, _shares_code_token

GOLF7_EA211_DESCS = [
    "Volkswagen Golf VII EA211 petrol 998cc 105–105hp manual (manual) (2017–2020)",
    "Volkswagen Golf VII EA211 petrol 1395cc 125–125hp manual (manual) (2013–2020)",
    "Volkswagen Golf VII EA211 petrol 1395cc 125–125hp automatic (dq200) (2013–2020)",
]


def test_exact_engine_code_match_grounds_without_llm():
    evidence = (
        "Source URL: https://enginescope.gr/engine/vw-ea211-14/\n"
        "EA211 1.4 TSI\n"
        "Timing belt — mandatory replacement — interference engine."
    )
    tokens = _code_tokens(evidence)
    assert "EA211" in tokens
    assert _shares_code_token(tokens, GOLF7_EA211_DESCS)


def test_transmission_code_match_grounds():
    evidence = "DQ200 mechatronics valve body cracking"
    tokens = _code_tokens(evidence)
    assert _shares_code_token(tokens, GOLF7_EA211_DESCS)  # dq200 appears in the dsg variant desc


def test_unrelated_code_does_not_ground():
    evidence = "K9K injector fouling on cold start"
    tokens = _code_tokens(evidence)
    assert tokens == {"K9K"}
    assert not _shares_code_token(tokens, GOLF7_EA211_DESCS)


def test_no_code_present_falls_through_to_llm_gate():
    evidence = "Generic turbo whine reported by several owners"
    tokens = _code_tokens(evidence)
    assert tokens == set()
    assert not _shares_code_token(tokens, GOLF7_EA211_DESCS)
