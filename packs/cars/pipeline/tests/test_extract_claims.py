"""packs.cars.pipeline.extract.extract_claims() — converts packs.cars.pipeline.langextract_client's
raw grounded-extraction dicts into CandidateClaim objects, skipping any
malformed one without sinking the whole batch. Mocks extract_grounded so this
runs with no API access (langextract's own wiring is covered by manual
smoke-testing against the real Mistral endpoint, same convention as
packs/cars/pipeline/judge.py's LLM gates).
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
def test_extract_claims_passes_only_first_6000_chars(mock_extract):
    mock_extract.return_value = []
    long_doc = Document(text="x" * 10000, url="https://x", site_or_channel="site")

    extract_claims(long_doc)

    (passed_text,), _ = mock_extract.call_args
    assert len(passed_text) == 6000


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
