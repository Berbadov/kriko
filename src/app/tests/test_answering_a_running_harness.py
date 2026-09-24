"""A reply that reaches the agent, not just the row.

`test_answering_a_running_job.py` proves the line gets as far as the handler.
That was the easy half, and on its own it was a note nobody read: every CLI
here ran one-shot, so the line went into a stdin with no reader on the other
end. These run a real child that speaks `--input-format stream-json` the way
`claude -p` does — it asks, it *blocks* until answered, and it does not exit
when its turn ends until its stdin closes — so the pipe's actual behaviour is
what is being tested, not a double's idea of it.
"""

import dataclasses
import sys

import pytest

from app.providers import harness as harness_mod
from app.providers.harness import HarnessResearcher, _asks, _is_result

#: A stand-in for `claude -p --output-format stream-json`. One-shot when not
#: told otherwise; conversational when handed `--input-format stream-json`, in
#: which case it reads its brief as the first message, asks a question, and
#: will not produce an answer until a second message arrives.
FAKE_CLI = r'''
import json, sys, time

args = sys.argv[1:]
if "--input-format" not in args:
    prompt = args[args.index("--") + 1] if "--" in args else sys.stdin.read()
    print(json.dumps({"type": "result", "result": "oneshot:" + prompt}), flush=True)
    sys.exit(0)

if MODE == "silent":
    time.sleep(120)
    sys.exit(0)

def text(message):
    return message["message"]["content"][0]["text"]

print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
brief = text(json.loads(sys.stdin.readline()))
if MODE == "asks":
    # What `claude -p` actually does with a question: it ends the turn on it.
    print(json.dumps({"type": "result", "result": "Which engine is it?"}), flush=True)
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    print(json.dumps({"type": "result",
                      "result": brief + "|" + text(json.loads(line))}), flush=True)
    sys.stdin.read()
    sys.exit(0)
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "text", "text": "Which engine is it?"}]}}), flush=True)
answer = text(json.loads(sys.stdin.readline()))
print(json.dumps({"type": "result", "result": brief + "|" + answer}), flush=True)
# What makes this a faithful double: a real stream-json child waits for the
# next turn rather than exiting. Only EOF ends it.
sys.stdin.read()
sys.exit(0)
'''


def _cli(tmp_path, mode="talks", declares=True):
    script = tmp_path / f"fake_claude_{mode}.py"
    script.write_text(f"MODE = {mode!r}\n" + FAKE_CLI, encoding="utf-8")
    return harness_mod.Harness(
        "fake",
        "Fake CLI",
        sys.executable,
        (str(script),),
        structured=True,
        reply_flag="--input-format" if declares else "",
        reply_value="stream-json" if declares else "",
    )


@pytest.fixture
def declares_streaming_input(monkeypatch):
    # `python` has no `--input-format`, so the probe is answered here the way
    # a current `claude --help` answers it.
    monkeypatch.setattr(
        harness_mod, "declared", lambda _executable: frozenset({"--input-format"})
    )


def _answers(*lines):
    """What the reader typed, handed over once, the way `take_job_messages` does."""
    pending = list(lines)

    def replies():
        taken = list(pending)
        pending.clear()
        return taken

    return replies


def test_the_answer_reaches_the_agent_and_changes_what_it_says(
    tmp_path, declares_streaming_input
):
    researcher = HarnessResearcher(_cli(tmp_path), timeout=30)
    researcher.replies = _answers("the 1.6 TDI")

    reply = researcher.ask("research this car")

    # Both halves in the one answer: the brief it was started on, and the
    # thing it could only have learned from the reader mid-run. And it came
    # back at all — a child that waits for another turn did not hang the run.
    assert "research this car|the 1.6 TDI" in reply
    assert "you: the 1.6 TDI" in researcher.actions


def test_a_turn_that_ends_on_a_question_waits_for_the_answer(
    tmp_path, declares_streaming_input
):
    # The answer is typed only once the question is on screen — after the
    # turn is over. Closing the pipe at `result` would have lost it.
    heard: list[str] = []
    researcher = HarnessResearcher(_cli(tmp_path, mode="asks"), timeout=30)
    typed: list[str] = []

    def replies():
        if "waiting for your answer" in heard and not typed:
            typed.append("the 1.6 TDI")
            return ["the 1.6 TDI"]
        return []

    researcher.replies = replies
    researcher.on_action = heard.append

    assert "research this car|the 1.6 TDI" in researcher.ask("research this car")


def test_a_question_nobody_answers_ends_the_run_with_what_it_had(
    tmp_path, monkeypatch, declares_streaming_input
):
    monkeypatch.setattr(harness_mod, "ANSWER_WAIT_SECONDS", 1.0)
    heard: list[str] = []
    researcher = HarnessResearcher(_cli(tmp_path, mode="asks"), timeout=30)
    researcher.replies = _answers()
    researcher.on_action = heard.append

    assert "Which engine is it?" in researcher.ask("research this car")
    assert "no answer came; the run ends here" in heard


def test_a_run_nobody_can_answer_stays_one_shot(tmp_path, declares_streaming_input):
    # No reply box, no pipe: the B125 risk is taken only where it buys something.
    researcher = HarnessResearcher(_cli(tmp_path), timeout=30)
    assert researcher.replies is None

    assert "oneshot:" in researcher.ask("research this car")


def test_a_cli_that_does_not_declare_the_flag_stays_one_shot(tmp_path, monkeypatch):
    # The reader's `claude` is not this machine's. An older build that never
    # heard of `--input-format` must lose the reply, not the run.
    monkeypatch.setattr(harness_mod, "declared", lambda _executable: frozenset())
    researcher = HarnessResearcher(_cli(tmp_path), timeout=30)
    researcher.replies = _answers("ignored")

    assert "oneshot:" in researcher.ask("research this car")


def test_a_reply_to_a_one_shot_run_is_marked_as_not_heard(tmp_path):
    # A CLI that reads stdin to EOF, the shape that hung six authoring tests
    # when a one-shot run was handed a pipe "in case". It must get no pipe,
    # finish, and the reader's line must say plainly that it went nowhere.
    script = tmp_path / "reads_stdin.py"
    script.write_text(
        "import json, sys, time\n"
        "sys.stdin.read()\n"
        "time.sleep(1.5)\n"
        "print(json.dumps({'type': 'result', 'result': 'done'}), flush=True)\n",
        encoding="utf-8",
    )
    one = harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script), "-p"), structured=True
    )
    heard: list[str] = []
    researcher = HarnessResearcher(one, timeout=30)
    researcher.replies = _answers("hello")
    researcher.on_action = heard.append

    assert "done" in researcher.ask("research this car")
    assert any(line.startswith("you: hello (not heard") for line in heard)


def test_a_child_that_never_speaks_is_retried_the_ordinary_way(
    tmp_path, monkeypatch, declares_streaming_input
):
    # The pipe that did not arrive. Abandoned at the start deadline rather
    # than at the timeout, and the run still happens — it just cannot be
    # answered, and the live feed says so.
    monkeypatch.setattr(harness_mod, "CONVERSATION_START_SECONDS", 1.0)
    heard: list[str] = []
    researcher = HarnessResearcher(_cli(tmp_path, mode="silent"), timeout=30)
    researcher.replies = _answers()
    researcher.on_action = heard.append

    assert "oneshot:" in researcher.ask("research this car")
    assert any("cannot be answered" in line for line in heard)


def test_only_a_claude_shaped_protocol_is_spoken_to(tmp_path, declares_streaming_input):
    # The framing belongs to the protocol. A CLI whose messages we do not
    # know how to write gets the one-shot vector, never a guess at JSON.
    other = dataclasses.replace(_cli(tmp_path), protocol="vibe")
    researcher = HarnessResearcher(other, timeout=30)
    researcher.replies = _answers("ignored")

    assert researcher._can_converse() is False


def test_the_turn_ends_on_the_result_event_and_nothing_else():
    assert _is_result('{"type": "result", "result": "x"}')
    assert not _is_result('{"type": "assistant"}')
    assert not _is_result("not json")
    assert not _is_result("[1, 2]")


def test_only_a_turn_ending_on_a_question_mark_is_a_question():
    assert _asks('{"type": "result", "result": "Which engine is it?  "}')
    assert not _asks('{"type": "result", "result": "Done. Is it? No."}')
    assert not _asks('{"type": "result"}')
    assert not _asks("?")
