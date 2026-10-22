"""The decision rule, the independence count and the fitted model.

These are the parts that decide whether a sentence counts as a recurrence, so
they are checked as behaviour: a contrast sentence never counts, a thin claim
is never expanded, near-copies are one source, and a fitted model separates the
labels it was fitted on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import claim_recurrence as cr  # noqa: E402


def features(**overrides: float) -> dict[str, float]:
    base = {"containment": 0.75, "shared": 3.0, "rare_shared": 2.0,
            "negation_mismatch": 0.0, "contrast": 0.0, "product_distance": 0.2,
            "log_length": 0.5, "window": 0.0, "embedding": 0.0}
    return {**base, **overrides}


def test_three_shared_words_at_half_the_weight_is_the_floor() -> None:
    assert cr.rule(features(), 4)
    assert not cr.rule(features(shared=2.0), 4)
    assert not cr.rule(features(containment=0.4), 4)


def test_a_claim_too_thin_to_share_three_words_is_never_expanded() -> None:
    assert not cr.rule(features(), 2)


def test_a_contrast_phrase_vetoes_the_rule_and_the_model() -> None:
    contrast = {"containment": 1.0, "shared": 3.0, "rare_shared": 3.0,
                "negation_mismatch": 0.0, "contrast": 1.0, "product_distance": 0.0,
                "log_length": 0.5, "window": 0.0, "embedding": 0.0}
    assert not cr.rule(contrast, 3)
    assert cr.Scorer(None, embedder_available=False).decide(contrast, 3) == (False, 0.0)


def test_a_claim_does_not_share_words_with_its_own_product() -> None:
    claim = cr.make_claim("the Dyson V11 trigger sticks", "Dyson V11", cr.stems)
    assert "trigge" in claim.stems
    assert "dyson" not in claim.stems


def test_near_copies_of_one_sentence_count_as_one_source() -> None:
    sentence = ("the trigger does not turn the vacuum off when released and the "
                "motor keeps running until the battery dies")
    groups = cr.independent_sources({
        "a.com": sentence,
        "b.com": sentence,
        "c.com": "the fence moves during every cut and will not stay aligned at all",
    })
    assert sorted(len(group) for group in groups) == [1, 2]


def test_the_control_probability_follows_the_two_rates() -> None:
    same = cr.prob_above_control(2, 4, 2, 4, samples=2000, seed=1)
    higher = cr.prob_above_control(4, 4, 0, 4, samples=2000, seed=1)
    assert 0.3 < same < 0.7
    assert higher > 0.9


def test_a_fitted_model_separates_the_labels_and_round_trips(tmp_path) -> None:
    rows = []
    for index in range(60):
        strong = index % 2 == 0
        rows.append({
            "url": f"https://site{index // 4}.com/page",
            "label": int(strong),
            "features": features(containment=0.9 if strong else 0.2,
                                 shared=4.0 if strong else 1.0,
                                 rare_shared=3.0 if strong else 0.0),
        })
    model, report = cr.train(rows)
    assert report["cv_f1"] >= 0.9
    assert model.probability(rows[0]["features"]) > model.probability(rows[1]["features"])

    path = tmp_path / "model.json"
    model.save(path)
    loaded = cr.load_model(path)
    assert loaded.features == model.features
    assert abs(loaded.probability(rows[0]["features"])
               - model.probability(rows[0]["features"])) < 1e-9


def test_training_refuses_a_label_set_that_cannot_be_folded_by_page() -> None:
    rows = [{"url": "https://one.com/page", "label": index % 2,
             "features": features()} for index in range(30)]
    with pytest.raises(ValueError, match="distinct pages"):
        cr.train(rows)


def test_a_thread_is_one_page_and_its_pagination_is_not_a_second() -> None:
    first = "https://www.ifixit.com/Answers/View/12345/trigger+stuck"
    second = first + "?page=2"
    assert cr.thread_of(first) == cr.thread_of(second)
    other = "https://www.ifixit.com/Answers/View/99999/other+fault"
    assert cr.thread_of(first) != cr.thread_of(other)
    assert not cr.is_discussion("https://example.com/review/dyson-v11")
    assert cr.is_discussion("https://board.example.com/viewtopic.php?t=99")


def test_three_threads_on_one_publisher_are_enough() -> None:
    sentence = "the trigger does not turn the vacuum off when released and the motor runs on"
    urls = [f"https://forum.example.com/threads/{number}/x" for number in (1, 2, 3)]
    record = cr.summarise({"forum.example.com": [(sentence, 1.0)]}, urls,
                          [{"url": url, "verdict": "matched"} for url in urls])
    assert record["recurring"]
    assert len(record["threads"]) == 3


def test_a_joined_pair_must_cover_more_of_the_claim_than_one_sentence() -> None:
    assert not cr.rule(features(window=1.0, containment=0.55), 5)
    assert cr.rule(features(window=1.0, containment=0.65), 5)


def test_a_bench_summary_reports_rates_and_stability() -> None:
    rows = [
        {"id": "true-a", "seconds": 2.0, "pages": 4, "sources": ["x"]},
        {"id": "true-a", "seconds": 4.0, "pages": 4, "sources": []},
        {"id": "false-b", "seconds": 6.0, "pages": 4, "sources": []},
        {"id": "true-c", "seconds": 0.0, "error": "search failed"},
    ]
    report = cr.summarise_runs(rows)
    assert report["runs"] == 4 and report["errors"] == 1
    assert report["true_found"] == 1 and report["true_runs"] == 2
    assert report["false_kept"] == 0 and report["false_runs"] == 1
    assert report["p50"] == 4.0 and report["p95"] == 6.0
    assert cr.stability(rows)["true-a"] == (2, 1)


def test_a_query_is_the_product_quoted_and_three_claim_words() -> None:
    queries = cr.queries_for(
        "Sony WH-1000XM4",
        "headphones connect briefly and then immediately disconnect")
    assert queries[0] == '"Sony WH-1000XM4" immediately headphones disconnect'
    assert queries[1].endswith("forum")
    assert "sony" not in queries[0].removeprefix('"Sony WH-1000XM4"')


def test_results_that_are_threads_about_the_model_rank_first() -> None:
    hits = [
        {"url": "https://shop.example/v11", "title": "Dyson V11 battery"},
        {"url": "https://www.reddit.com/r/dyson/comments/a/b", "title": "trigger stuck"},
        {"url": "https://example.com/blog", "title": "vacuum tips"},
    ]
    ordered = cr.rank_hits(hits, "Dyson V11",
                           "the trigger does not turn the vacuum off when released")
    assert ordered[0]["url"].startswith("https://www.reddit.com")


def test_a_possibility_is_not_a_report() -> None:
    claim = cr.make_claim("the trigger does not turn the vacuum off when released",
                          "Dyson V11", cr.stems)
    terms = cr.product_terms("Dyson V11")
    scorer = cr.Scorer(None, embedder_available=False)
    speculative = ("The Dyson V11 is covered here. Outdated firmware might lead to a trigger "
                   "that does not turn the vacuum off when released, according to the vendor.")
    assert cr.judge_page(scorer, claim, speculative, terms, None)[0] is None
    reported = ("The Dyson V11 is covered here. My trigger does not turn the vacuum off when "
                "released, so it keeps running until I pull the battery.")
    assert cr.judge_page(scorer, claim, reported, terms, None)[0] is not None
