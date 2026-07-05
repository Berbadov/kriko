"""Cross-manufacturer code contamination guard — a claim naming another
manufacturer's engine/transmission code (with no brand word at all, just
jargon like "EA211"/"TSI") must not ride the deterministic gate_variant
bypass in on a mismatched code mention.

Regression: h4d_75.yaml (Renault) carried a claim whose own rationale said
"the turbocharger in the 1.0 TSI (EA211) engine" — a Volkswagen engine, not
Renault's H4D. Neither the sibling-code guard (same-manufacturer families
only) nor promote.py's brand-name guard (the text never says "Volkswagen")
could see this. Found + retroactively purged 2026-07-05 (see
docs/design_flaws.md); this guard is the process fix so it doesn't
recur — the registry it checks against is read off the live catalog, not a
hand-maintained list.
"""

from unittest.mock import patch

import pytest

from knowledge.extract import CandidateClaim
from knowledge.judge import GateResult
from knowledge.parts.validate_part_yaml import validate_part
from knowledge.promote import Disposition, promote
from knowledge.sources.base import Document
from knowledge.stoplists import catalog_code_manufacturers, mentions_foreign_manufacturer_code

H4D_VARIANTS = [
    ("clio5_h4d_75", "Renault Clio 5 H4D petrol 999cc 75hp manual (h4d_75) (2019-present)"),
]


@pytest.fixture(autouse=True)
def _fresh_catalog_cache():
    # catalog_code_manufacturers() is lru_cache'd against the real on-disk
    # catalog — clear before/after so no test run leaves a stale cache for
    # whatever runs next in the same process.
    catalog_code_manufacturers.cache_clear()
    yield
    catalog_code_manufacturers.cache_clear()


def test_catalog_code_manufacturers_derives_from_real_part_yaml():
    owners = catalog_code_manufacturers()
    assert owners["EA211"] == frozenset({"volkswagen"})
    assert owners["H4D"] == frozenset({"renault"})
    # H5H is co-developed with Daimler — both tokens present, not just "renault".
    assert owners["H5H"] == frozenset({"renault", "daimler"})


def test_mentions_foreign_manufacturer_code_catches_the_live_regression():
    # The exact wording that was live in h4d_75.yaml before this guard existed.
    text = "The turbocharger in the 1.0 TSI (EA211) engine exhibits accelerated wear."
    assert mentions_foreign_manufacturer_code(text, {"renault"})


def test_mentions_foreign_manufacturer_code_allows_own_manufacturer():
    assert not mentions_foreign_manufacturer_code(
        "H4D turbocharger wear under city driving", {"renault"}
    )


def test_mentions_foreign_manufacturer_code_allows_daimler_co_development():
    # H5H's own manufacturer field is "renault_daimler" — a Renault-context
    # claim mentioning it is not foreign, it's the same JV engine.
    assert not mentions_foreign_manufacturer_code("H5H ignition coil wear", {"renault"})


def test_mentions_foreign_manufacturer_code_ignores_unregistered_and_non_code_text():
    assert not mentions_foreign_manufacturer_code("Rough idle and poor fuel economy", {"renault"})


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
@patch("knowledge.promote.gate_variant", return_value=GateResult(False, "different manufacturer"))
def test_foreign_manufacturer_code_does_not_bypass_llm_gate(_gv, _gi, _gg):
    claim = CandidateClaim(
        title="Timing belt degradation in oil bath (EA211 evo)",
        domain="engine",
        severity="high",
        rationale="In EA211 evo versions, the timing belt operates in an oil bath.",
        inspection_advice="Check for oil pickup clogging.",
        quote="EA211 evo timing belt in oil bath",
    )
    doc = Document(text="1.0 TSI EA211 timing belt design", url="https://x/ea211", site_or_channel="site")
    results = promote([(claim, doc)], H4D_VARIANTS, own_part_id="h4d_75")
    r = results[0]
    assert r.disposition == Disposition.HELD
    assert r.reason == "gate_variant: no variant grounded"


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
def test_uncontaminated_h4d_claim_still_bypasses_llm(_gi, _gg):
    claim = CandidateClaim(
        title="H4D turbocharger premature wear",
        domain="engine",
        severity="medium",
        rationale="H4D turbocharger wears prematurely under sustained city driving.",
        inspection_advice="Check for whistling noise on acceleration.",
        quote="H4D turbo wear reported",
    )
    doc = Document(text="Renault Clio 5 H4D turbo issue", url="https://x/h4d", site_or_channel="site")
    results = promote([(claim, doc)], H4D_VARIANTS, own_part_id="h4d_75")
    assert results[0].grounded_variant_ids == ["clio5_h4d_75"]


def test_validate_part_flags_foreign_manufacturer_code():
    import tempfile
    from pathlib import Path

    import yaml

    data = {
        "part_id": "h4d_75",
        "part_type": "engine",
        "display_name": "Renault H4D 75hp",
        "manufacturer": "renault",
        "claims": [{
            "claim_key": "h4d_75_engine_timing_belt_degradat",
            "title": "Timing belt degradation in oil bath (EA211 evo)",
            "kind": "known_issue",
            "domain": "engine",
            "severity": "high",
            "status": "held",
            "rationale": "In EA211 evo versions, the timing belt operates in an oil bath.",
            "inspection_advice": "Check for clogging.",
            "sources": [],
        }],
    }
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "h4d_75.yaml"
        path.write_text(yaml.dump(data))
        errors = validate_part(path)
    assert any("another manufacturer" in e for e in errors)
