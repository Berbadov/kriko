"""Cross-brand contamination guard — a claim naming a different manufacturer
must not ride the deterministic gate_variant bypass in on an unrelated code
mention elsewhere in a multi-brand source page.

Regression test: a "Ford 7DCT 300 Clutch Squeak" claim reached `review`
(servable) status in dc4.yaml (a Renault EDC/DC4 transmission part file) —
the source was a multi-brand DCT comparison video whose transcript mentioned
"DC4"/"EDC" elsewhere, so the code-token bypass (which checks the FULL
source text) wrongly granted it a free pass.
"""

from unittest.mock import patch

from knowledge.extract import CandidateClaim
from knowledge.judge import GateResult
from knowledge.promote import Disposition, _mentions_other_brand, promote
from knowledge.sources.base import Document

DC4_VARIANTS = [
    ("megane4_h5f_100", "Renault Megane IV DC4 petrol 1197cc 100hp automatic (dc4) (2016-present)"),
]


def test_mentions_other_brand_detects_ford():
    assert _mentions_other_brand("7DCT 300 Clutch Squeak (Ford)", {"renault"})


def test_mentions_other_brand_ignores_dacia():
    # Dacia is Renault's own badge-engineered sibling — shares engines/gearboxes
    # verbatim, so a Dacia mention is legitimate evidence, not contamination.
    assert not _mentions_other_brand("Known issue on Dacia Duster with DC4", {"renault"})


def test_mentions_other_brand_ignores_own_make():
    assert not _mentions_other_brand("Renault Megane DC4 issue", {"renault"})


def test_mentions_other_brand_ignores_vw_group_siblings():
    # Audi/Skoda/Seat share MQB-era engines and DSG gearboxes with VW verbatim.
    assert not _mentions_other_brand("DQ250 hydraulic issues (Audi A3 8P chassis)", {"volkswagen"})


def test_mentions_other_brand_still_catches_non_sibling_on_vw_part():
    assert _mentions_other_brand("Known Toyota Corolla issue with this part", {"volkswagen"})


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
@patch("knowledge.promote.gate_variant", return_value=GateResult(False, "different manufacturer"))
def test_contaminated_claim_does_not_bypass_llm_gate(_gv, _gi, _gg):
    # Source page transcript mentions DC4 (a real code), but the specific
    # claim is explicitly about Ford's own 7DCT 300 unit.
    claim = CandidateClaim(
        title="7DCT 300 Clutch Squeak/Friction Noise (Ford)",
        domain="transmission",
        severity="medium",
        rationale="Ford's 7DCT 300 dry dual-clutch transmission exhibits a squeak on 3rd-4th shifts.",
        inspection_advice="Listen for squeak during 3rd-to-4th upshift.",
        quote="7DCT 300 squeak on 3-4 upshift",
    )
    doc = Document(
        text="Comparing DCT reliability across brands: Ford 7DCT 300, Renault DC4 EDC, VW DQ200 all discussed.",
        url="https://x/dct-comparison",
        site_or_channel="site",
    )
    results = promote([(claim, doc)], DC4_VARIANTS)
    r = results[0]
    # gate_variant (mocked to reject) was actually consulted, not bypassed —
    # confirmed by the HELD disposition despite "DC4" appearing in doc.text.
    assert r.disposition == Disposition.HELD
    assert r.reason == "gate_variant: no variant grounded"


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
def test_uncontaminated_code_match_still_bypasses_llm(_gi, _gg):
    # Sanity check: a genuine DC4 claim with no other-brand mention still
    # gets the deterministic bypass (no gate_variant mock needed — if this
    # fell through to the real LLM call without an API key, it would raise).
    claim = CandidateClaim(
        title="DC4 clutch pack wear",
        domain="transmission",
        severity="medium",
        rationale="DC4 dual-clutch transmission clutch pack wears prematurely.",
        inspection_advice="Check for shudder on takeoff.",
        quote="DC4 clutch pack wear reported",
    )
    doc = Document(text="DC4 transmission clutch pack issue", url="https://x/dc4", site_or_channel="site")
    results = promote([(claim, doc)], DC4_VARIANTS)
    assert results[0].grounded_variant_ids == ["megane4_h5f_100"]
