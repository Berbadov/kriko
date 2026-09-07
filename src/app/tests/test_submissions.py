"""What a researcher submitted, and what happened to it.

`app/findings.py` refuses most of what arrives — that is the whole point of the
gate — but until now the refusals were returned to the caller and then dropped
on the floor. They are the highest-signal data anyone has for improving the
research skill: the same reason, a hundred times, is a prompt bug, not a
hundred bad findings.

Two doors share one acceptance path (MCP and the in-app research job), so the
door is recorded: the first question about a bad batch is which of them made it.
"""

import pytest

from app.findings import log_submission
from app.web import state


@pytest.fixture
def conn(tmp_path):
    return state.connect(tmp_path / "app.sqlite")


VERDICTS = {
    "accepted": ["a"],
    "rejected": [
        {"title": "one", "reason": "no source — add a quote from a real page"},
        {"title": "two", "reason": "no source — add a quote from a real page"},
        {"title": "three", "reason": "subject not in the pack"},
    ],
}


def test_a_batch_records_both_halves_and_its_door(conn):
    state.record_submission(
        conn, door="mcp", subject_id="s1", pack_id="p", verdicts=VERDICTS
    )
    (row,) = state.submissions(conn)
    assert row["door"] == "mcp"
    assert (row["accepted"], row["refused"]) == (1, 3)
    assert row["verdicts"]["rejected"][0]["title"] == "one"


def test_an_unknown_door_is_coerced_rather_than_raising(conn):
    state.record_submission(
        conn, door="carrier pigeon", subject_id="s1", pack_id="p", verdicts={}
    )
    # Bookkeeping must never be the reason a finding is lost, so a caller
    # inventing a door gets logged, not rejected.
    assert state.submissions(conn)[0]["door"] == "job"


def test_refusals_are_tallied_by_the_rule_not_by_the_advice(conn):
    state.record_submission(
        conn, door="job", subject_id="s1", pack_id="p", verdicts=VERDICTS
    )
    reasons = state.refusal_reasons(conn)
    # Grouped on the clause the gate wrote; everything after the em dash is
    # advice about that one finding and would make every reason unique.
    assert reasons[0] == {"reason": "no source", "count": 2}
    assert {"reason": "subject not in the pack", "count": 1} in reasons


def test_batches_come_back_newest_first(conn):
    for subject in ("first", "second"):
        state.record_submission(
            conn, door="job", subject_id=subject, pack_id="p", verdicts={}
        )
    assert [row["subject_id"] for row in state.submissions(conn)] == [
        "second",
        "first",
    ]


def test_logging_never_raises_when_the_ledger_is_unreachable(tmp_path):
    # An author losing the refusal log must never cost a researcher an accepted
    # finding, so this path swallows everything.
    unreachable = tmp_path / "no-such-dir" / "app.sqlite"
    log_submission(
        unreachable, door="mcp", subject_id="s", pack_id="p", verdicts=VERDICTS
    )


def test_the_endpoint_answers_with_the_reasons_beside_the_batches(tmp_path):
    from fastapi.testclient import TestClient

    from app.web.app import create_app
    from app.web.settings import Settings

    settings = Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )
    log_submission(
        settings.app_state_path,
        door="mcp",
        subject_id="s1",
        pack_id="p",
        verdicts=VERDICTS,
    )
    body = TestClient(create_app(settings)).get("/api/submissions").json()
    assert body["accepted"] == 1
    assert body["refused"] == 3
    # A list of batches without the histogram is a log; the histogram is the
    # part that tells an author what to change.
    assert body["reasons"][0]["reason"] == "no source"
    assert len(body["items"]) == 1
