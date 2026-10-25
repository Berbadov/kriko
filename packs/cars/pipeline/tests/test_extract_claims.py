"""packs.cars.pipeline.extract.extract_claims() — converts packs.cars.pipeline.langextract_client's
raw grounded-extraction dicts into CandidateClaim objects, reads the whole
document in overlapping chunks, and skips any malformed claim without sinking
the whole batch. Mocks extract_grounded so this runs with no API access
(langextract's own wiring is covered by manual smoke-testing against the real
endpoint, same convention as packs/cars/pipeline/judge.py's LLM gates).
"""

from unittest.mock import patch

from packs.cars.pipeline.extract import CandidateClaim, extract_claims
from packs.cars.pipeline.sources.base import Document

_DOC = Document(text="some source text " * 10, url="https://x", site_or_channel="site")


@patch("packs.cars.pipeline.extract.extract_grounded")
def test_extract_claims_converts_grounded_dicts(mock_extract):
    mock_extract.return_value = [{
        "title": "Thermostat housing cracking (H5H 1.3 TCe)",
        "domain": "cooling",
        "severity": "high",
        "rationale": "Housing cracks around 80,000 km.",
        "inspection_advice": "Check for coolant seepage around the housing.",
        "quote": "the thermostat housing is prone to cracking",
        "engine_or_variant_hint": "H5H",
        "quote_grounded": True,
    }]

    claims = extract_claims(_DOC)

    assert len(claims) == 1
    assert isinstance(claims[0], CandidateClaim)
    assert claims[0].title == "Thermostat housing cracking (H5H 1.3 TCe)"
    assert claims[0].quote_grounded is True


@patch("packs.cars.pipeline.extract.extract_grounded")
def test_the_tail_of_a_long_document_is_read(mock_extract):
    """The old 6,000-character cap silently lost this claim."""
    mock_extract.return_value = []
    tail = " After 120,000 km the water pump bearing failed and the engine overheated."
    long_doc = Document(text=("The owner is happy with the car. " * 220) + tail,
                        url="https://x", site_or_channel="site")

    extract_claims(long_doc)

    passed = [call.args[0] for call in mock_extract.call_args_list]
    assert any("water pump bearing failed" in text for text in passed)


@patch("packs.cars.pipeline.extract.extract_grounded")
def test_a_signal_free_middle_chunk_is_not_paid_for(mock_extract):
    mock_extract.return_value = []
    long_doc = Document(text="x" * 12_000, url="https://x", site_or_channel="site")

    extract_claims(long_doc)

    # Opening and closing chunks are always read; the two middle chunks carry
    # no failure signal and are skipped.
    assert len(mock_extract.call_args_list) == 2


@patch("packs.cars.pipeline.extract.extract_grounded")
def test_a_claim_repeated_by_the_chunk_overlap_is_one_claim(mock_extract):
    claim = {
        "title": "Water pump bearing failure (K9K)",
        "domain": "cooling",
        "severity": "high",
        "rationale": "The bearing fails and the engine overheats.",
        "inspection_advice": "Listen for bearing noise and check for coolant loss.",
        "quote": "the water pump bearing failed",
        "quote_grounded": True,
    }
    mock_extract.return_value = [claim]
    # Two chunks, with 'fail' as the signal in the second one.
    long_doc = Document(text=("x" * 4_000) + " the water pump bearing failed " + ("x" * 1_000),
                        url="https://x", site_or_channel="site")

    claims = extract_claims(long_doc)

    assert len(claims) == 1


@patch("packs.cars.pipeline.extract.extract_grounded")
def test_extract_claims_skips_malformed_without_sinking_batch(mock_extract):
    mock_extract.return_value = [
        {"title": "missing required fields"},  # malformed — no domain/severity/etc.
        {
            "title": "Good claim (K9K)",
            "domain": "engine",
            "severity": "medium",
            "rationale": "r",
            "inspection_advice": "a",
            "quote": "q",
            "quote_grounded": False,
        },
    ]

    claims = extract_claims(_DOC)

    assert len(claims) == 1
    assert claims[0].title == "Good claim (K9K)"


@patch("packs.cars.pipeline.extract.extract_grounded")
def test_extract_claims_defaults_quote_grounded_false_when_absent(mock_extract):
    mock_extract.return_value = [{
        "title": "Claim without grounding info",
        "domain": "engine",
        "severity": "low",
        "rationale": "r",
        "inspection_advice": "a",
        "quote": "q",
    }]

    claims = extract_claims(_DOC)

    assert claims[0].quote_grounded is False
