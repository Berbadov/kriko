"""few_shot_examples() — built from knowledge/gold/gold.yaml's `verdict: correct`
entries only. No API calls here (that's covered by manual smoke-testing per
docs/pipeline_postmortem.md convention — LLM gates/extraction aren't
unit-tested against a live endpoint); this just verifies the example-building
logic against the real, on-disk gold set.
"""

import yaml

from knowledge.langextract_client import GOLD_PATH, few_shot_examples


def test_few_shot_examples_only_includes_correct_verdicts():
    few_shot_examples.cache_clear()
    entries = yaml.safe_load(GOLD_PATH.read_text()) or []
    expected_correct = sum(1 for e in entries if e.get("verdict") == "correct" and e.get("quote", "").strip())

    examples = few_shot_examples()

    assert len(examples) == expected_correct
    assert expected_correct > 0  # sanity: gold.yaml actually has correct entries to learn from


def test_few_shot_examples_text_matches_extraction_text_exactly():
    # langextract's prompt-alignment validator requires each example's
    # extraction_text to be an exact substring of its own text — verify our
    # examples satisfy that (a bad gold.yaml entry would otherwise crash
    # extract_grounded() at call time, not at gold.yaml edit time).
    few_shot_examples.cache_clear()
    for ex in few_shot_examples():
        assert ex.extractions[0].extraction_text in ex.text


def test_few_shot_examples_carry_required_attributes():
    few_shot_examples.cache_clear()
    for ex in few_shot_examples():
        attrs = ex.extractions[0].attributes
        assert attrs["title"]
        assert attrs["domain"]
        assert attrs["severity"] in ("high", "medium", "low")
        assert attrs["rationale"]
