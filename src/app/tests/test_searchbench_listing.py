import pytest

from app.searchbench.listing import fact_f1_proxy, summarize


def test_f1_proxy_penalizes_unknown_claims_and_keeps_missing_grades_unknown():
    audit = {"status": "scored", "fact_recall": 1,
             "detail": {"claims": [{"correct": True}, {"correct": None}]}}
    score, precision, recall = fact_f1_proxy(audit)
    assert precision == .5 and recall == 1
    assert score == pytest.approx(2 / 3)
    assert fact_f1_proxy({"status": "no_answer"}) == (0, 0, 0)
    assert fact_f1_proxy({"status": "judge_error"}) is None


def test_f1_proxy_keeps_failed_research_and_excludes_identity_tasks():
    correct = {"status": "scored", "fact_recall": 1, "detail": {"claims": [{"correct": True}]}}
    failed = {"status": "no_answer"}
    rows = []
    for job, audit, accepted in [("easy", correct, True), ("heavy", failed, False), ("identity", correct, True)]:
        rows.append({"profile": "candidate", "complexity": job, "audits": {"a": audit, "b": audit},
                     "accuracy": {"accepted": accepted}, "total_s": 2, "known_cost_usd": .01,
                     "cost_complete": True, "known_tokens": {"total": 100}, "tokens": {"total": 100}})
    result = summarize(rows)[0]
    assert result["f1"] == .5 and result["f1_n"] == 2 and result["factual_n"] == 2
    assert result["accepted"] == 2 and result["n"] == 3
    assert result["cost"] == .01 and result["tokens"] == 100
