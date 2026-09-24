"""The fourth CLI, and the gate that makes a fifth cost what it should.

The reader's report was "detected harnesses aren't including the all", and
they were right: GitHub Copilot CLI was installed, on their `PATH`, logged in
and answering prompts, and `available()` named three agents. Not a discovery
bug — there was no row for it at all.

One row is the fix for one CLI. The mechanism is below it: every protocol a
row names must have a sample stream here, and that sample must narrate. A
future CLI whose output shape nobody wrote a parser for now fails the suite
while it is being added, rather than at the end of a ten-minute run on the
reader's own subscription.

Every Copilot fixture here was captured from GitHub Copilot CLI 1.0.48 — the
event names, the nesting under `data`, the `arguments` key and the terminal
`result` line are transcribed, not invented. "Protocol" here is the output
dialect a harness speaks; `test_protocols.py` is about the other one.
"""

import json

import pytest

from app.providers import harness


def _stream(*events: dict) -> str:
    return "".join(json.dumps(one) + "\n" for one in events)


COPILOT_REPLY = _stream(
    {"type": "session.mcp_servers_loaded", "data": {"servers": []}},
    {"type": "session.tools_updated", "data": {"model": "gpt-4.1"}},
    {"type": "assistant.message_delta",
     "data": {"messageId": "m1", "deltaContent": "The "}},
    {"type": "assistant.message",
     "data": {"messageId": "m1", "model": "gpt-4.1",
              "content": 'The title is "Example Domain".',
              "toolRequests": [{"name": "web_fetch", "toolCallId": "c1",
                                "arguments": {"url": "https://example.com",
                                              "max_length": 5000}}]}},
    {"type": "assistant.turn_end", "data": {"turnId": "0"}},
    {"type": "result", "exitCode": 0,
     "usage": {"premiumRequests": 0, "sessionDurationMs": 5667}},
)

COPILOT_FAILURE = _stream(
    {"type": "session.tools_updated", "data": {"model": "a-model"}},
    {"type": "model.call_failure",
     "data": {"model": "a-model", "statusCode": 400,
              "errorMessage": "The requested model is not supported."}},
    {"type": "assistant.turn_end", "data": {"turnId": "0"}},
    {"type": "result", "exitCode": 1, "usage": {"premiumRequests": 0}},
)

#: One "the agent read a page" event per protocol any row names. A tool call
#: rather than a sentence, because that is the event every one of these CLIs
#: has and the one a reader watching a ten-minute run is actually waiting for
#: — the model's own prose arrives as fragments on two of them and is joined
#: by `HarnessResearcher._say`, which is a buffer rather than a parser.
#:
#: The dict is the gate: a new CLI whose protocol is not a key here fails
#: `test_every_protocol_a_row_names_has_a_parser` below, which is the cheapest
#: possible moment to discover that nothing can read its output.
FETCHED = {
    "claude": {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "WebFetch",
         "input": {"url": "https://example.com"}}]}},
    "agy": {"event": "step_update", "step_update": {
        "step_type": "tool", "state": "DONE",
        "tool_info": {"name": "WebFetch",
                      "parameters": {"Url": "https://example.com"}}}},
    "vibe": {"type": "effect", "sessionId": "s1",
             "generationStatus": "completed",
             "title": "fetched https://example.com"},
    "gemini": {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "WebFetch",
         "input": {"url": "https://example.com"}}]}},
    "copilot": {"type": "assistant.message", "data": {
        "content": "", "toolRequests": [
            {"name": "web_fetch", "arguments": {"url": "https://example.com"}}]}},
}


def _copilot() -> harness.Harness:
    return next(one for one in harness.KNOWN if one.id == "github-copilot")


def _reader(one: harness.Harness) -> harness.HarnessResearcher:
    """A researcher with only the field `_unwrap` reads, and no run behind it."""
    reader = harness.HarnessResearcher.__new__(harness.HarnessResearcher)
    reader.harness = one
    return reader


def test_the_reply_is_the_assistant_messages_not_the_result_line():
    """Copilot's `result` carries an exit code and no reply text at all."""
    assert _reader(_copilot())._unwrap(COPILOT_REPLY) == 'The title is "Example Domain".'


def test_a_failure_reported_at_exit_zero_is_still_a_failure():
    with pytest.raises(RuntimeError) as raised:
        _reader(_copilot())._unwrap(COPILOT_FAILURE)
    assert "not supported" in str(raised.value)


def test_prose_survives_a_shape_nobody_predicted():
    """The findings fence may still be in it — see `_unwrap_vibe`."""
    assert _reader(_copilot())._unwrap("not json at all") == "not json at all"


def test_the_log_says_what_it_fetched_and_what_it_said():
    said = [one for one in
            (harness.narrate(json.loads(line))
             for line in COPILOT_REPLY.splitlines()) if one]
    assert "started gpt-4.1" in said
    assert "fetched https://example.com" in " ; ".join(said)
    # The delta frames are the same sentence arriving one word at a time.
    assert not any(one.strip() == "The" for one in said)


def test_the_two_web_tools_read_the_same_whichever_cli_spelled_them():
    assert harness._tool_line("WebFetch", {"url": "https://a.example"}) == (
        harness._tool_line("web_fetch", {"url": "https://a.example"}))
    assert harness._tool_line("WebSearch", {"query": "q"}) == (
        harness._tool_line("web_search", {"query": "q"}))


@pytest.mark.parametrize("one", harness.KNOWN, ids=lambda one: one.id)
def test_every_protocol_a_row_names_has_a_parser(one):
    """The mechanism, not the row: a fifth CLI cannot be added silently.

    A protocol with no sample here is a protocol nobody has read output for,
    and the failure it would otherwise produce is the expensive one — an
    empty reply at the end of a real run, on the reader's own subscription.
    """
    assert one.protocol in FETCHED, (
        f"{one.id} names protocol {one.protocol!r}, which has no sample "
        f"event in FETCHED and therefore no evidence anything can read it")
    assert "example.com" in harness.narrate(FETCHED[one.protocol]), (
        f"a {one.protocol!r} agent's page reads are invisible in the job log")


def test_the_new_row_declares_what_it_cannot_do():
    """No web search tool, so the contract must say so rather than assume."""
    copilot = _copilot()
    assert "web-search" not in copilot.capabilities
    assert copilot.contract_note.strip(), (
        "a harness whose tools differ from the shared contract must say how")
    assert "web_fetch" in copilot.args, "the tool grant is the sandbox"


def test_the_prompt_is_a_flag_value_and_the_vector_is_sandboxed():
    copilot = _copilot()
    assert copilot.prompt_flag == "-p" and not copilot.prompt_argument
    for flag in ("--allow-all-tools", "--no-ask-user", "--available-tools",
                 "--disable-builtin-mcps", "--no-custom-instructions"):
        assert flag in copilot.args, f"{flag} is what makes this run headless"


def test_every_row_says_where_to_get_it_and_what_it_bills():
    """The missing-harness card is the only screen a reader without one sees."""
    for one in harness.KNOWN:
        assert one.download_url and one.needs_account, (
            f"{one.id} would appear on the missing-harness card with nothing "
            f"to click and no account named")
