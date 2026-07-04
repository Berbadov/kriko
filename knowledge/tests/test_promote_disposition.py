"""_evaluate_claim disposition rules — severity-high / gate_refute overrides.

Regression test: a `severity: high` claim (or one gate_refute disagreed on)
used to always land on `review` regardless of score, even when ZERO sources
passed gate_support — writing a servable claim with an empty `sources:` list
(caught live in backend/data/parts/transmission/dq200.yaml, which
validate_part_yaml.py rejects: "servable non-maintenance claim has no
sources"). It must fall back to `held` when there is truly no corroborating
evidence, and keep the original "force review" behavior once at least one
source supports it.
"""

from typing import Literal
from unittest.mock import patch

from knowledge.extract import CandidateClaim
from knowledge.judge import GateResult
from knowledge.promote import Disposition, promote
from knowledge.sources.base import Document

VARIANTS = [("megane4_k9k_90", "Renault Megane IV K9K diesel 1461cc 90hp manual (2016-present)")]


def _claim(severity: Literal["high", "medium", "low"] = "high"):
    return CandidateClaim(
        title="K9K injector fouling on cold start",
        domain="engine",
        severity=severity,
        rationale="Injectors foul on cold starts, chronic on K9K.",
        inspection_advice="Check for rough cold idle.",
        quote="K9K injectors are known to foul",
    )


def _doc(url="https://x/1", site="site", text="K9K injector text"):
    return Document(text=text, url=url, site_or_channel=site)


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
def test_high_severity_zero_sources_is_held_not_review(_gi, _gg):
    with patch("knowledge.promote.gate_support", return_value=GateResult(False, "no support")):
        results = promote([(_claim("high"), _doc())], VARIANTS)
    assert len(results) == 1
    r = results[0]
    assert r.disposition == Disposition.HELD
    assert r.grounded_sources == []


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
def test_high_severity_with_one_source_still_forces_review(_gi, _gg):
    with patch("knowledge.promote.gate_support", return_value=GateResult(True, "supports")), \
         patch("knowledge.promote.gate_refute", return_value=GateResult(True, "not refuted")):
        results = promote([(_claim("high"), _doc())], VARIANTS)
    r = results[0]
    assert r.disposition == Disposition.REVIEW
    assert len(r.grounded_sources) == 1


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
def test_refute_conflict_zero_sources_is_held_not_review(_gi, _gg):
    # gate_support passes but gate_refute disagrees on the only source →
    # override_review would trip with score still 0.
    with patch("knowledge.promote.gate_support", return_value=GateResult(True, "supports")), \
         patch("knowledge.promote.gate_refute", return_value=GateResult(False, "contradicts")):
        results = promote([(_claim("medium"), _doc())], VARIANTS)
    r = results[0]
    assert r.disposition == Disposition.HELD
    assert r.grounded_sources == []


@patch("knowledge.promote.gate_generic", return_value=GateResult(True, "not generic"))
@patch("knowledge.promote.gate_inspection_value", return_value=GateResult(True, "high value"))
def test_refute_conflict_with_a_second_supporting_source_forces_review(_gi, _gg):
    # Two sources: one supports cleanly (score=1), the other conflicts.
    # override_review is set, and score >= 1 → REVIEW, not HELD.
    calls = {"n": 0}

    def _support(*a, **k):
        calls["n"] += 1
        return GateResult(True, "supports")

    def _refute(*a, **k):
        # First call: refutes (conflict). Second call: does not.
        return GateResult(calls["n"] != 1, "checked")

    with patch("knowledge.promote.gate_support", side_effect=_support), \
         patch("knowledge.promote.gate_refute", side_effect=_refute):
        results = promote(
            [
                (_claim("medium"), _doc("https://a/1", site="site-a", text="K9K injector text, forum thread A")),
                (_claim("medium"), _doc("https://b/1", site="site-b", text="K9K injector text, repair blog B")),
            ],
            VARIANTS,
        )
    r = results[0]
    assert r.disposition == Disposition.REVIEW
    assert len(r.grounded_sources) == 1
