"""Agent write gates — the product principle enforced at the write path.

Calibration matters as much as the rules: run against the 699 claims already
in the catalog, these gates reject ~10 rows, and each of those is a row
CLAUDE.md says should never have been surfaced ("Clutch Slippage", "Ball joint
excessive play", "Recurrent front suspension failures"). A gate that rejected
real chronics would make the agent path unusable, so the escape valves
(specificity signal, recall) are tested as hard as the rejections.
"""

from knowledge.agent import gates

GOOD_RATIONALE = ("The dry-clutch DQ200 mechatronic unit fails past 120,000 km, "
                  "leaving the car unable to select a gear. Replacement is a "
                  "four-figure repair on a car of this value.")


def _check(title, rationale=GOOD_RATIONALE, advice="Listen for jerky shifts.",
           hint="dq200", url=""):
    return gates.check_evidence(title, rationale, advice, hint, url)


# ── what must pass ───────────────────────────────────────────────────────────

def test_a_real_chronic_passes_clean():
    res = _check("DQ200 mechatronic unit failure")
    assert res.ok and res.warnings == []


def test_dual_clutch_wear_passes_because_the_title_names_the_unit():
    """'clutch wear' is inspection-covered on a manual, a chronic on a DSG."""
    assert _check("DQ381 clutch pack wear at high mileage").ok


def test_a_recall_passes_even_when_it_names_an_inspected_part():
    assert gates.check_evidence(
        "Front brake disc cracking risk (recall)",
        "A manufacturer recall covers front brake discs that crack in service "
        "on affected build dates; the repair is free at a dealer.",
        "Check the VIN against the recall list.", "clio5_body").ok


def test_mileage_anchor_rescues_an_ambiguous_term():
    assert gates.check_evidence(
        "Oil consumption past 100,000 km on this engine",
        "Piston-ring wear drives measurable oil consumption past 100,000 km on "
        "this engine family, and topping up hides it between services.",
        "Ask for oil top-up frequency.", "ea211").ok


# ── what must be rejected ────────────────────────────────────────────────────

def test_generic_warning_light_is_rejected():
    res = gates.check_evidence("ABS warning light", GOOD_RATIONALE, "x", "dq200")
    assert not res.ok and any("warning-light" in r for r in res.rejections)


def test_bare_inspection_covered_title_is_rejected():
    res = _check("Clutch slip")
    assert not res.ok and any("ekspertiz" in r for r in res.rejections)


def test_dtc_litany_title_is_rejected():
    res = _check("P0299 P2263 turbo underboost faults")
    assert not res.ok and any("DTC" in r for r in res.rejections)


def test_filler_rationale_is_rejected():
    res = _check("DQ200 mechatronic failure", rationale="It can break.")
    assert not res.ok and any("rationale" in r for r in res.rejections)


def test_claim_with_no_config_anchor_is_rejected():
    res = gates.check_evidence(
        "Engine can develop problems",
        "The engine sometimes develops problems as it gets older, and repairs "
        "can be expensive depending on what has gone wrong.",
        "Have it looked at.", None)
    assert not res.ok and any("specific config" in r for r in res.rejections)


def test_verbose_title_is_rejected():
    res = _check("A very long title " * 12)
    assert not res.ok and any("chars" in r for r in res.rejections)


# ── warnings ride along, they never block ────────────────────────────────────

def test_weak_source_tier_warns_but_does_not_reject():
    res = _check("DQ200 mechatronic unit failure", url="https://randomblog.example/x")
    assert res.ok and any("tier" in w for w in res.warnings)


def test_missing_inspection_advice_only_warns():
    res = _check("DQ200 mechatronic unit failure", advice="")
    assert res.ok and any("inspection_advice" in w for w in res.warnings)


# ── document gate ────────────────────────────────────────────────────────────

def test_blocked_forum_source_is_rejected():
    res = gates.check_document("https://vwvortex.com/threads/1", "x" * 400, "dq200")
    assert not res.ok and any("blocked source" in r for r in res.rejections)


def test_snippet_instead_of_article_text_is_rejected():
    res = gates.check_document("https://asrgearboxrepairs.co.uk/x", "too short")
    assert not res.ok and any("raw_text" in r for r in res.rejections)


def test_research_budget_is_enforced_server_side():
    res = gates.check_document("https://asrgearboxrepairs.co.uk/x", "x" * 400,
                               "dq200", existing_for_target=5, max_per_target=5)
    assert not res.ok and any("budget" in r for r in res.rejections)


def test_specialist_source_carries_no_tier_warning():
    res = gates.check_document("https://asrgearboxrepairs.co.uk/x", "x" * 400, "dq200")
    assert res.ok and res.warnings == []


# ── calibration against the live catalog ─────────────────────────────────────

def test_gates_do_not_reject_the_bulk_of_the_existing_catalog():
    """A gate that fails good rows makes the agent path unusable. Pin the rate."""
    import pathlib

    import yaml

    total = rejected = 0
    parts = pathlib.Path(__file__).resolve().parents[2] / "packs" / "cars" / "data" / "parts"
    for path in parts.rglob("*.yaml"):
        data = yaml.safe_load(path.read_text()) or {}
        for claim in data.get("claims") or []:
            total += 1
            if not gates.check_evidence(claim.get("title", ""),
                                        claim.get("rationale", ""),
                                        claim.get("inspection_advice", ""),
                                        data.get("part_id")).ok:
                rejected += 1
    assert total > 100
    assert rejected / total < 0.05, f"{rejected}/{total} existing claims rejected"
