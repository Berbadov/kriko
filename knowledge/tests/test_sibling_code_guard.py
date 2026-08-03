"""Sibling-code contamination guard — a claim naming a different physical
component in the same manufacturer family (DQ200 vs DQ381, K9K vs H4D, ...)
must not ride the deterministic gate_variant bypass in on an unrelated code
mention elsewhere in a multi-code comparison source page.

Regression: DQ200 dry-clutch/accumulator claims (codes P189C/P17BF/P0841)
reached `review` status in backend/data/parts/transmission/dq381.yaml (a
wet-clutch gearbox that does not have those failure modes) because the
code-token bypass checks the FULL source text, and a DSG comparison article
mentions "DQ381" somewhere too. See docs/design_flaws.md Flaw 1.

The guard lives on: sync's part-YAML validator (validate_part_yaml) and the
ledger verdict prompt both consume it — the promote-pipeline flow tests were
removed with the judge/promote stack at the B16 swap (2026-08-03).
"""

from knowledge.parts.validate_part_yaml import validate_part
from knowledge.stoplists import mentions_sibling_code, sibling_codes_for


def test_sibling_codes_for_dq381_excludes_own_code():
    assert sibling_codes_for("dq381") == frozenset({"DQ200", "DQ250"})


def test_sibling_codes_for_ea888_220_resolves_base_code():
    # Power-tune-suffixed part_id still resolves to its family via the base code.
    assert sibling_codes_for("ea888_220") == frozenset({"EA211", "EA288"})


def test_sibling_codes_for_unregistered_part_is_empty():
    assert sibling_codes_for("golf7_body") == frozenset()


def test_sibling_codes_for_h5h_includes_h5f():
    # Regression: H5F was missing from the Renault small-engine family, so a
    # claim about the H5F engine could sit undetected in h5h_130.yaml and
    # reach a Clio 5 H5H buyer (found live in production data this session).
    assert "H5F" in sibling_codes_for("h5h")


def test_sibling_codes_for_r9m_and_m9r_are_registered_siblings():
    # Regression: R9M/M9R (Renault-Nissan-Mercedes 1.6/2.0 dCi) had no family
    # at all, so R9M/M9R claims mislabeled under h5h_130.yaml went undetected.
    # The M9R alias lives in code_family_extra on the merged r9m part — the
    # B16 swap must preserve it (it was lost once, caught by this test).
    assert {"M9R", "H5H"} <= sibling_codes_for("r9m")
    assert {"R9M", "H5H"} <= sibling_codes_for("m9r")


def test_mentions_sibling_code_detects_dq200_in_dq381_text():
    assert mentions_sibling_code("DQ200 dry-clutch pressure circuit failure", "dq381")


def test_mentions_sibling_code_ignores_own_code_comention():
    # Text names both codes (e.g. explicit contrast) — not the silent
    # mislabeling failure mode this guards against.
    assert not mentions_sibling_code("DQ381 vs DQ200 clutch design differences", "dq381")


def test_mentions_sibling_code_ignores_unrelated_text():
    assert not mentions_sibling_code("Mechatronic unit water ingress corrosion", "dq381")


def test_validate_part_flags_sibling_contaminated_claim():
    # Build a minimal part YAML on disk so validate_part's real YAML-loading
    # path is exercised as-is.
    import tempfile
    from pathlib import Path

    import yaml

    data = {
        "part_id": "dq381",
        "part_type": "transmission",
        "display_name": "Volkswagen DQ381 Transmission",
        "manufacturer": "volkswagen",
        "claims": [{
            "claim_key": "dq381_transmission_dq200_dry-clutch",
            "title": "DQ200 dry-clutch pressure circuit failure (accumulator/pump)",
            "kind": "known_issue",
            "domain": "transmission",
            "severity": "high",
            "status": "review",
            "rationale": "The DQ200 dry-clutch DSG suffers from chronic hydraulic pressure issues.",
            "inspection_advice": "Check for hesitation.",
            "sources": [{"source_url": "https://x", "quote": "q"}],
        }],
    }
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "dq381.yaml"
        path.write_text(yaml.dump(data))
        errors = validate_part(path)
    assert any("sibling" in e.lower() for e in errors)


# ── Uncatalogued family codes (live-probe finding) ──────────────────────────
#
# The guard is catalog-derived, so it can only reason about codes the catalog
# carries. A claim citing DQ500 — a gearbox Kriko has NEVER onboarded — was
# therefore invisible to it, and got served on a DQ250 car ("High Torque Wear in
# the DQ500 Transmission (Golf R, Audi S3, RS Models)"). A code that looks like
# one of our families but names a component we do not carry is, by definition,
# not about the part it is filed under. Same own-code-absent escape hatch as the
# sibling rule: co-mentioning our own code is legitimate contrast.
# definition, not about the part it is filed under. Same own-code-absent escape
# hatch as the sibling rule: co-mentioning our own code is legitimate contrast.

def test_uncatalogued_family_code_is_contamination():
    # DQ500 shares the DQ family shape but is not in the catalog.
    assert mentions_sibling_code(
        "High Torque Wear in the DQ500 Transmission (Golf R, Audi S3)", "dq250") is True


def test_uncatalogued_family_code_with_own_code_is_legitimate_contrast():
    # Names DQ500 but also its own DQ381 — a genuine cross-generation comparison.
    assert mentions_sibling_code(
        "DQ381/DQ500 mechatronic valve and sticky sensor issues", "dq381") is False


def test_uncatalogued_engine_family_code_is_contamination():
    # EA189 (dieselgate 2.0 TDI) is not the EA288 it is filed under.
    assert mentions_sibling_code(
        "EGR fouling leading to rough idle and smoke on the EA189", "ea288") is True


def test_foreign_family_code_in_unrelated_part_is_contamination():
    # A Renault engine file citing VW's EA111.
    assert mentions_sibling_code(
        "Timing chain tensioner failure (EA111)", "h5h_130") is True


def test_catalogued_code_is_not_flagged_as_uncatalogued():
    # DQ250 IS in the catalog: this must stay a plain sibling decision, and a
    # claim naming only its own code is clean.
    assert mentions_sibling_code("DQ250 mechatronic unit failure", "dq250") is False


def test_non_family_code_token_is_not_contamination():
    # Sensor/DTC codes (G28, N75, P0401) share no catalog family prefix and must
    # never be mistaken for a foreign component code.
    assert mentions_sibling_code(
        "Fault code P0401 with G28 sensor and N75 valve on the DQ250", "dq250") is False
