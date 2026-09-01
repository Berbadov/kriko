"""ground_year_window() — deterministic grounding guard for model-year windows.

An LLM (or any upstream) may *propose* a model-year window on a claim. Before
that window is trusted at the serving gate (where it silently HIDES claims from
cars outside the window), each bound must be grounded in the cited source text:
the year token must actually appear AND a direction-appropriate cue word must
sit near it. An ungrounded bound is dropped (→ open on that side), which only
ever WIDENS the window — the fail-open-safe direction. So a hallucinated bound
can never narrow the window past what the evidence supports.
"""

from packs.cars.pipeline.claims.ground_year_window import ground_year_window


def test_grounded_lower_and_upper_are_both_kept():
    r = ground_year_window(2019, 2022, "Fault affects 2019 builds, fixed in 2022.")
    assert r.year_from == 2019
    assert r.year_to == 2022


def test_ungrounded_upper_is_dropped_to_open():
    # Source only evidences the lower bound; 2022 never appears.
    r = ground_year_window(2019, 2022, "Fault affects 2019 builds onward.")
    assert r.year_from == 2019
    assert r.year_to is None  # upper opened — claim stays visible on newer cars


def test_year_present_but_no_cue_is_dropped():
    # The classic false positive: 2022 appears, but as a date-of-mention, not a
    # fix boundary. No upper-bound cue near it → not evidence of a fix.
    r = ground_year_window(None, 2022, "As of 2022 the model was very popular.")
    assert r.year_to is None


def test_wrong_direction_cue_does_not_ground_a_bound():
    # "affects" is a LOWER cue; it must not ground an UPPER bound.
    r = ground_year_window(None, 2019, "Fault affects 2019 builds.")
    assert r.year_to is None


def test_turkish_lower_cue_grounds():
    r = ground_year_window(2020, None, "Arıza 2020 itibaren görülüyor.")
    assert r.year_from == 2020


def test_word_boundary_rejects_embedded_year():
    # 2022 appears only inside the part number 20225 — not a standalone token,
    # even though an upper cue ("revised") is present.
    r = ground_year_window(None, 2022, "Part number 20225 was revised.")
    assert r.year_to is None


def test_single_year_keeps_only_the_evidenced_half():
    # "fixed in 2021" evidences an upper bound (≤2021) but not a lower one, so a
    # proposed [2021,2021] is sanitized to the evidenced half, widening down.
    r = ground_year_window(2021, 2021, "Issue fixed in 2021.")
    assert r.year_from is None
    assert r.year_to == 2021


def test_none_inputs_pass_through_with_empty_report():
    r = ground_year_window(None, None, "anything")
    assert r.year_from is None
    assert r.year_to is None
    assert r.report == {}


def test_empty_source_drops_all_proposed_bounds():
    r = ground_year_window(2019, 2022, "")
    assert r.year_from is None
    assert r.year_to is None


def test_report_records_kept_and_dropped_per_bound():
    r = ground_year_window(2019, 2022, "Fault affects 2019 builds onward.")
    assert r.report["from"] == "kept"
    assert r.report["to"].startswith("dropped")
