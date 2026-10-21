"""Failures are classified from what the run left behind, and counted.

The reader's list for the local plane was malformed JSON, a paraphrased quote
refused by grounding, an ignored requirement and an invented link. The classes
are derived, never entered by hand, and a paraphrase stays refused: the
classifier names the failure, it does not excuse it.
"""

import json

import pytest

from app.tuning import failures

PAGE = ("Widget MK2 owners report that the hydraulic pump failed after a month of use. "
        "The tyres are covered by a separate warranty.")


def _reply(**claim):
    base = {"title": "Pump failure", "why": "w", "severity": "high",
            "url": "https://a.test/1", "quote": "the hydraulic pump failed after a month"}
    return json.dumps({"risks": [{**base, **claim}], "specs": []})


def test_a_quote_the_page_carries_is_no_finding():
    assert failures.classify_reply(_reply(), {"https://a.test/1": PAGE}) == []


def test_a_reworded_quote_is_a_paraphrase_not_an_invention():
    found = failures.classify_reply(
        _reply(quote="the hydraulic pump broke down after one month"),
        {"https://a.test/1": PAGE})
    assert [one["class"] for one in found] == ["paraphrased_quote"]


def test_a_quote_unlike_anything_on_the_page_is_an_invention():
    found = failures.classify_reply(
        _reply(quote="owners say the gearbox overheats badly under sustained towing"),
        {"https://a.test/1": PAGE})
    assert [one["class"] for one in found] == ["invented_quote"]


def test_an_address_the_model_was_never_shown_is_an_invented_link():
    found = failures.classify_reply(_reply(url="https://made-up.test/x"),
                                    {"https://a.test/1": PAGE})
    assert [one["class"] for one in found] == ["invented_link"]


def test_a_reply_with_no_object_is_malformed_not_clean():
    found = failures.classify_reply("I found a pump failure but wrote prose.",
                                    {"https://a.test/1": PAGE})
    assert [one["class"] for one in found] == ["malformed_json"]


@pytest.mark.parametrize("message,expected", [
    ("http://x did not answer within 60 s", "timeout"),
    ("The instructions for this task take 9000 characters, which leaves no room for evidence.",
     "context_too_small"),
    ("Task leaves no context for evidence; increase local context.", "context_too_small"),
    ("No evidence pass completed: Model returned invalid structured evidence.", "no_evidence"),
    ("Model returned invalid structured evidence.", "malformed_json"),
    ("something else broke", "runtime_error"),
    ("", ""),
])
def test_an_error_message_names_its_class(message, expected):
    assert failures.classify_error(message) == expected


def test_a_failed_check_maps_to_its_class_and_a_quote_finding_decides_the_quote_class():
    trial = {"error": "", "checks": [
        {"name": "honest_proposals", "status": "fail", "detail": ""},
        {"name": "output_language", "status": "fail", "detail": ""},
        {"name": "recall", "status": "pass", "detail": ""}],
        "quote_findings": [{"class": "paraphrased_quote"}]}
    assert failures.classify_trial(trial) == ["paraphrased_quote", "ignored_requirement"]


def test_a_failed_grounding_check_with_no_finding_is_an_invented_quote():
    trial = {"error": "", "checks": [{"name": "grounded", "status": "fail", "detail": ""}],
             "quote_findings": []}
    assert failures.classify_trial(trial) == ["invented_quote"]


def test_counting_names_the_commonest_class_and_counts_a_row_in_each_of_its_classes():
    rows = [{"failures": ["paraphrased_quote", "ignored_requirement"]},
            {"failures": ["paraphrased_quote"]},
            {"failures": ["invented_link"]}, {"failures": []}]
    counts = failures.tally(rows)
    assert counts == {"paraphrased_quote": 2, "invented_link": 1, "ignored_requirement": 1}
    assert failures.commonest(counts) == "paraphrased_quote"
    assert failures.commonest({}) == ""


# ── the agent benchmark counts them ─────────────────────────────────────────

@pytest.fixture(scope="module")
def flawed_matrix():
    from app.agentbench import runner, suite

    return runner.run_bench(suite.load()["tasks"],
                            ["sim:fabricator", "sim:english", "sim:injected", "sim:oracle"],
                            reps=1, profile="clean")


def _classes(matrix, agent):
    return {name for trial in matrix["trials"] if trial["agent"] == agent
            for name in trial["failures"]}


def test_a_fabricated_quote_is_counted_as_an_invented_quote(flawed_matrix):
    assert "invented_quote" in _classes(flawed_matrix, "sim:fabricator")


def test_an_ignored_language_is_counted_as_an_ignored_requirement(flawed_matrix):
    assert "ignored_requirement" in _classes(flawed_matrix, "sim:english")


def test_an_obeyed_page_order_is_counted(flawed_matrix):
    assert "obeyed_page_instruction" in _classes(flawed_matrix, "sim:injected")


def test_the_faultless_agent_has_no_failure_class_and_the_report_says_so(flawed_matrix):
    from app.agentbench import report

    assert _classes(flawed_matrix, "sim:oracle") == set()
    summary = report.summarize(flawed_matrix)
    assert summary["agents"]["sim:oracle"]["failure_classes"] == {}
    assert summary["agents"]["sim:fabricator"]["commonest_failure"] == "invented_quote"
    text = report.render(summary)
    assert "Why trials failed, by class" in text
    assert "invented_quote" in text
