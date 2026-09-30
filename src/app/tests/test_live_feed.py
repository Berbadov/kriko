"""B176: the dark panel's events, and how soon a line reaches the log.

"Within about a second of the CLI printing it": the first test runs a real
child that prints one tool call and then keeps going, and measures the gap
between the child's own clock and the moment the log hears about it. The rest
pin the classifier to the narrator's real output.
"""

import json
import sys
import time

import pytest

from app.providers import harness as harness_mod
from app.providers.harness import HarnessResearcher, _tool_line
from app.web import livefeed
from app.web.routers import jobs as jobs_router

FAKE = r'''
import json, sys, time
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "WebFetch",
     "input": {"url": "https://example.test/t=%r" % time.time()}}]}}), flush=True)
time.sleep(20)
'''


class _Stop(Exception):
    pass


def test_a_printed_action_reaches_the_log_within_a_second(tmp_path):
    script = tmp_path / "fake_streaming.py"
    script.write_text(FAKE, encoding="utf-8")
    one = harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script),), structured=True
    )
    researcher = HarnessResearcher(one, timeout=30)
    heard: list[tuple[float, str]] = []
    researcher.on_action = lambda line: heard.append((time.time(), line))

    def check():
        if any("example.test" in line for _, line in heard):
            raise _Stop

    researcher.check_cancelled = check
    with pytest.raises(_Stop):
        researcher.ask("go")
    at, line = next((at, line) for at, line in heard if "example.test" in line)
    printed = float(line.rsplit("t=", 1)[1])
    assert at - printed < 1.0, f"the log heard it {at - printed:.2f}s after it was printed"


def test_the_stream_polls_fast_enough_to_keep_the_second():
    # The log write is immediate; what remains is the stream's own poll, which
    # adds up to one interval on top of everything else.
    assert jobs_router.POLL_SECONDS <= 0.25


def test_the_narrators_own_lines_are_classified():
    lines = "\n".join([
        _tool_line("WebSearch", {"query": "e-bike motor faults"}),
        _tool_line("WebFetch", {"url": "https://example.test/a"}),
        _tool_line("mcp__reader__" + harness_mod.READER_TOOLS[0],
                   {"urls": ["https://example.test/b"]}),
        "kept “Motor cuts out” as c-1",
        "refused “Vague”: no page",
        "a tool call failed: timeout",
        "plane: agent",
    ])
    kinds = [e["kind"] for e in livefeed.feed_of(lines)]
    assert kinds == ["search", "source", "source", "finding", "problem", "problem", "note"]


def test_two_actions_joined_by_the_narrator_are_two_events():
    joined = "; ".join([
        _tool_line("WebFetch", {"url": "https://example.test/a"}),
        _tool_line("WebFetch", {"url": "https://example.test/b"}),
    ])
    assert [e["kind"] for e in livefeed.feed_of(joined)] == ["source", "source"]


def test_a_running_job_carries_its_feed_and_a_finished_one_does_not():
    live = {"log": "fetched https://example.test/a\n", "done": False, "result": None}
    done = {"log": "fetched https://example.test/a\n", "done": True, "result": None}
    assert jobs_router._with_attention(live)["feed"][0]["kind"] == "source"
    assert "feed" not in jobs_router._with_attention(done)
    json.dumps(live)


def test_the_sources_slider_becomes_a_ceiling_in_the_brief():
    from app.web import tasks

    assert tasks._source_ceiling({}) == ""
    assert tasks._source_ceiling({"max_documents": 0}) == ""
    assert "at most 12 sources" in tasks._source_ceiling({"max_documents": 12})
    assert "at most 1 source " in tasks._source_ceiling({"max_documents": 1})


def test_the_author_request_takes_and_bounds_the_source_count():
    from pydantic import ValidationError

    assert jobs_router.AuthorRequest(category="e-bikes", max_documents=8).max_documents == 8
    with pytest.raises(ValidationError):
        jobs_router.AuthorRequest(category="e-bikes", max_documents=51)
