"""The plane that closes the loop, and the gate on a run that finds nothing.

Two rows land here, and they are one story.

**B92.** Kriko shipped two research planes and neither of them could drive an
agent. `AgentResearcher.gather()` returns `[]` by design — something else is
meant to read the brief — and `app/agentconfig.py` teaches a harness how to
*call* Kriko. Nothing anywhere called a harness. So a reader who pressed
Research on 0.5.3 got `succeeded / 0 claim(s) kept` with a log that ended at
`gathered 0 document(s)`, which is indistinguishable from a dead button. The
fix is `app/providers/harness.py`: run the CLI the reader already pays for,
headlessly, and file what it says.

**B93.** And the log has to say so. Three different runs produced the same
`0 claim(s) kept` — a plane that never fetches, a plane that fetched and found
nothing, and a plane whose every finding was refused — and none of them is
actionable without knowing which. `EMPTY_RUN` keys the sentence by plane so a
fourth plane cannot be added without deciding what its empty run means.

**B105.** Then the reader pressed the pack-authoring button on 0.7.1 and got
`RuntimeError: Claude Code exited 1: [{"type":"system","subtype":"init",...`
— two thousand characters of tool list, session id and model, and not one word
about why. Two things were wrong. The detail was the *front* of the CLI's
output when the reason is always at the back; and their build prints the whole
message stream as a JSON array under `--output-format json` while this one
prints the result object alone, so `_unwrap` was reading a shape that never
arrives on their machine. Their init banner also said
`"mcp_servers":[{"name":"kriko","status":"failed"}]`, which is how "the
spawned agent gets no MCP config" was found to mean "gets the reader's own".

The security gate is the one worth reading twice. The spawned agent is granted
`WebSearch` and `WebFetch` and nothing else, and it is handed no MCP config at
all: a research plane that can write files or run shell commands is not a
research plane, and one that could call `submit_findings` would let claims
arrive by a door the job that started it cannot see.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.providers import harness as harness_mod
from app.providers.harness import CONTRACT, HarnessResearcher, NoHarness, _payload
from app.web import tasks
from app.web.settings import Settings
from kriko.research.base import ResearchTask
from kriko.store.db import connect

# ── the security boundary ────────────────────────────────────────────────────

#: Anything on this list in a grant would make the plane a remote-code path.
FORBIDDEN = (
    "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Task", "Agent",
)


def test_the_spawned_agent_is_granted_search_and_nothing_else():
    """An allowlist, checked by name rather than by intent.

    A denylist would be the wrong shape here — a CLI that adds a tool next
    month would have it granted by default — so the assertion is on the exact
    tuple, and it fails if anyone widens it.
    """
    assert harness_mod.SEARCH_TOOLS == ("WebSearch", "WebFetch")
    for tool in FORBIDDEN:
        assert tool not in harness_mod.SEARCH_TOOLS


def test_every_known_harness_passes_that_allowlist_on_the_command_line():
    """The grant has to reach the process, not just the module.

    `SEARCH_TOOLS` being narrow is worth nothing if the argument vector omits
    `--allowedTools` — the CLI's own default would then decide, and its default
    is not ours to rely on.
    """
    for one in harness_mod.KNOWN:
        args = " ".join(one.args)
        for tool in FORBIDDEN:
            assert tool not in args, f"{one.id} grants {tool}"
        # A structured harness is one we drive with flags; a prose one (whose
        # only mode is `run`) gets no grant to widen.
        if "--allowedTools" in one.args:
            index = one.args.index("--allowedTools")
            assert one.args[index + 1] == ",".join(harness_mod.SEARCH_TOOLS)


def test_no_harness_puts_the_prompt_on_the_command_line():
    """The defect that made B92 ship a plane that could not run at all.

    `claude --help` declares `--allowedTools <tools...>` — a *variadic*
    option, which consumes every argument that follows it. The vector ended
    `--allowedTools WebSearch,WebFetch <prompt>`, so the brief was read as two
    more tool names and the CLI was left with no prompt. The reader waited out
    a run and got:

        Claude Code exited 1: Error: Input must be provided either through
        stdin or as a prompt argument when using --print

    Asserted as an invariant of the table rather than of one entry, because
    the bug is not "this flag is variadic" — it is "an argument vector has an
    order and a prompt has no place in one". Stdin has no order.
    """
    for one in harness_mod.KNOWN:
        for arg in one.args:
            assert "{" not in arg and "prompt" not in arg.lower(), (
                f"{one.id} looks like it interpolates the prompt into its "
                "arguments; it goes on stdin"
            )


def test_the_code_that_starts_a_harness_writes_the_prompt_to_stdin():
    """Read off the source, because the call site is the whole claim.

    A table with no prompt in it proves nothing on its own: `_run` could still
    append one. This is a text assertion and it knows it — the test below runs
    the real CLI, which is what actually holds.
    """
    source = Path(harness_mod.__file__).read_text(encoding="utf-8")
    assert "stdin=stdin_read" in source
    assert "*self.harness.args, prompt]" not in source


@pytest.mark.skipif(
    not shutil.which("claude"), reason="no Claude Code on this machine"
)
def test_the_harness_command_line_is_one_the_cli_accepts():
    """Run the real CLI, for free, and let it judge the vector.

    Every other gate in this file asserts the *shape* of `args`. None of them
    asserted the CLI would accept them, which is how a plane that could not
    start passed a full suite — the same mistake as the twelve tray tests that
    passed on a `main.rs` that could not be parsed (B89).

    `command_for` rather than `one.args`, since B105: the hygiene flags are
    resolved against this machine's `--help`, and a vector the test never sees
    is a vector nothing judges.

    The trick that makes this free: with an empty prompt, `claude -p` refuses
    before it makes any API call, and its complaint is *specifically* about the
    missing prompt. A malformed vector fails differently and earlier —
    `unknown option '--allowedToolz'`, or `argument 'jsonx' is invalid`. So
    "the only thing it objected to was the empty prompt" is exactly the
    assertion "everything else in this vector is accepted", at no cost and
    with no network.

    It skips where the CLI is absent and never passes there.
    """
    one = harness_mod.chosen("claude-code")
    assert one is not None
    done = subprocess.run(  # noqa: S603 - fixed executable, no shell
        harness_mod.command_for(one),
        input="",
        capture_output=True,
        text=True,
        timeout=120,
        cwd=os.path.expanduser("~"),
    )
    said = (done.stderr or "") + (done.stdout or "")
    assert "unknown option" not in said, said[:400]
    assert "is invalid" not in said, said[:400]
    # And the one complaint it is allowed to have, which is the one this
    # command deliberately provoked.
    assert "Input must be provided" in said, said[:400]


def test_every_offered_harness_has_a_tool_grant():
    """Every entry in `KNOWN` either restricts its tools or is `unusable`.

    `claude` restricts via `--allowedTools`. `opencode` restricts via
    `--agent`, naming a profile (`_ensure_opencode_agent`) whose own
    `permission:` block denies `bash`/`edit` and allows only
    `webfetch`/`websearch` — the same shape as `.opencode/agents/
    kriko_research.md` already ships in this repo.
    """
    for one in harness_mod.KNOWN:
        has_grant = (
            "--allowedTools" in one.args
            or "--allowed-tools" in one.args
            or "--agent" in one.args
        )
        assert has_grant or one.unusable, (
            f"{one.id} is offered with no way to restrict its tools"
        )
    assert all(one.unusable == "" for one in harness_mod.available())


def test_the_opencode_agent_profile_denies_bash_and_edit(tmp_path, monkeypatch):
    target = tmp_path / "kriko-harness.md"
    monkeypatch.setattr(harness_mod, "_OPENCODE_AGENT_PATH", target)
    harness_mod._ensure_opencode_agent()
    body = target.read_text(encoding="utf-8")
    assert "bash: deny" in body
    assert "edit: deny" in body
    assert "webfetch: allow" in body
    assert "websearch: allow" in body


def test_the_spawned_agent_is_handed_no_mcp_config():
    """No `--mcp-config`, anywhere, on purpose.

    The alternative design — hand the agent Kriko's own tools — was rejected:
    findings would then be written by the agent while the job that started it
    reported zero, and `tasks.py`'s "kept …"/"refused …" lines would still
    never be written. Findings come back on stdout instead.
    """
    for one in harness_mod.KNOWN:
        assert "--mcp-config" not in one.args
    assert "submit_findings" in CONTRACT  # named, to tell the agent NOT to
    assert "no Kriko tools" in CONTRACT


# ── driving a real subprocess ────────────────────────────────────────────────


def _fake_cli(tmp_path: Path, envelope: dict, *, exit_code: int = 0) -> harness_mod.Harness:
    """A CLI that answers exactly like `claude -p --output-format json`.

    A real subprocess rather than a monkeypatched `subprocess.run`: the thing
    most likely to be wrong here is the argument vector and the envelope shape,
    and a patched call tests neither.
    """
    reply = tmp_path / f"reply-{exit_code}-{len(str(envelope))}.json"
    reply.write_text(json.dumps(envelope), encoding="utf-8")
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import pathlib, sys\n"
        f"sys.stdout.write(pathlib.Path({str(reply)!r}).read_text())\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script), "-p"), structured=True
    )


def _task(**over) -> ResearchTask:
    base = dict(
        subject_id="s1",
        subject_label="Thing s1",
        subject_kind="product",
        pack_id="probe",
        queries=("{label} common problems",),
        domains=("engine",),
        max_documents=3,
    )
    return ResearchTask(**{**base, **over})


PAGE = (
    "Owners report that the timing chain kit on this engine is unobtainable in "
    "some markets. Several have waited months for the part."
)
QUOTE = "the timing chain kit on this engine is unobtainable in some markets"


def _reply(findings: list[dict], **extra) -> dict:
    return {
        "type": "result",
        "result": "Here is what I found.\n\n```json\n"
        + json.dumps({"findings": findings})
        + "\n```",
        "usage": {"input_tokens": 1200, "output_tokens": 340,
                  "cache_read_input_tokens": 9000},
        "total_cost_usd": 0.0,
        **extra,
    }


def test_what_the_cli_prints_becomes_documents_and_findings(tmp_path):
    """The whole point of the plane, in one assertion.

    `gather` parses; `extract` hands back what `gather` already parsed, per
    document. No second model call — the reading was done by the process that
    just exited.
    """
    fake = _fake_cli(
        tmp_path,
        _reply([
            {
                "title": "Timing chain kit unobtainable",
                "domain": "engine",
                "severity": "high",
                "quote": QUOTE,
                "document_text": PAGE,
                "source_url": "https://forum.example/thread/1",
                "component": "timing chain kit",
            },
            {
                "title": "Second finding on the same page",
                "domain": "engine",
                "severity": "medium",
                "quote": "Several have waited months for the part",
                "document_text": PAGE,
                "source_url": "https://forum.example/thread/1",
            },
        ]),
    )
    researcher = HarnessResearcher(fake, timeout=60)
    documents = researcher.gather(_task())

    # One document per source, not one per finding: two findings from one page
    # are two findings and one source, and counting them as two sources would
    # inflate the corroboration a claim looks like it has.
    assert len(documents) == 1
    assert documents[0].url == "https://forum.example/thread/1"
    assert documents[0].site_or_channel == "forum.example"
    assert QUOTE in documents[0].text

    found = researcher.extract(_task(), documents[0])
    assert [f.title for f in found] == [
        "Timing chain kit unobtainable",
        "Second finding on the same page",
    ]
    assert found[0].component == "timing chain kit"


def test_the_plane_reports_what_the_run_used(tmp_path):
    """B97's number, arriving for free.

    `tokens_used` is read duck-typed by `tasks.py`, and the reason the other $0
    plane leaves it NULL is that it genuinely cannot count. This one can, so
    leaving it NULL would be a lie in the other direction.
    """
    fake = _fake_cli(tmp_path, _reply([], total_cost_usd=0.42))
    researcher = HarnessResearcher(fake, timeout=60)
    researcher.gather(_task())
    assert researcher.tokens_used == 1200 + 340 + 9000
    assert researcher.cost_usd == 0.42


def test_a_finding_with_no_quote_never_becomes_a_document(tmp_path):
    """Refused here rather than at the acceptance path, for the same reason.

    `app/findings.py` would refuse it anyway — "trust me" is not an evidence
    model — but a document with no checkable text in it is not a source, and
    manufacturing one would make the run's source count wrong as well.
    """
    fake = _fake_cli(
        tmp_path,
        _reply([
            {"title": "No quote", "domain": "engine", "severity": "high",
             "source_url": "https://forum.example/2", "document_text": PAGE},
            {"title": "", "domain": "engine", "severity": "high",
             "quote": QUOTE, "document_text": PAGE,
             "source_url": "https://forum.example/3"},
        ]),
    )
    researcher = HarnessResearcher(fake, timeout=60)
    assert researcher.gather(_task()) == []
    assert researcher.note


def test_a_cli_that_fails_fails_the_run(tmp_path):
    """Loudly. A plane that swallowed a non-zero exit would report `succeeded`
    on a machine where the agent is not logged in, which is the 0.5.3 defect
    wearing a new hat."""
    fake = _fake_cli(tmp_path, {"result": "boom"}, exit_code=3)
    with pytest.raises(RuntimeError, match="exited 3"):
        HarnessResearcher(fake, timeout=60).gather(_task())


def test_an_error_reply_fails_the_run_even_with_a_zero_exit(tmp_path):
    """`claude -p` reports its own failures in the envelope, exit code 0."""
    fake = _fake_cli(
        tmp_path,
        {"type": "result", "is_error": True, "result": "credit balance too low"},
    )
    with pytest.raises(RuntimeError, match="credit balance"):
        HarnessResearcher(fake, timeout=60).gather(_task())


# ── B105: the failure a reader can read, and the shape they got ─────────────


def _fake_stream(tmp_path: Path, messages: list, *, exit_code: int = 0):
    """A CLI that answers the way the reader's build does: a JSON array.

    `[{"type":"system","subtype":"init",...}, ..., {"type":"result",...}]`,
    printed whole under `--output-format json`. Written as a real subprocess
    for the same reason `_fake_cli` is: the shape of the output is the thing
    under test and a patched `subprocess.run` would test neither.
    """
    reply = tmp_path / f"stream-{exit_code}-{len(str(messages))}.json"
    reply.write_text(json.dumps(messages), encoding="utf-8")
    script = tmp_path / "fake_stream.py"
    script.write_text(
        "import pathlib, sys\n"
        f"sys.stdout.write(pathlib.Path({str(reply)!r}).read_text())\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script), "-p"), structured=True
    )


#: The reader's init banner, abbreviated but the same shape and the same
#: leading position. Two thousand characters of this is what they were shown
#: instead of a reason.
BANNER = {
    "type": "system",
    "subtype": "init",
    "cwd": "C:\\Users\\beraat",
    "session_id": "01275c13-0919-4642-9a96-62235ac7911f",
    "tools": ["Task", "Bash", "Edit", "Read", "WebFetch", "WebSearch", "Write"],
    "mcp_servers": [{"name": "kriko", "status": "failed"}],
    "model": "claude-sonnet-5",
    "padding": "x" * 3000,
}


def test_the_reason_a_run_failed_is_what_the_reader_is_shown(tmp_path):
    """Not the init banner. This is B105 in one assertion.

    The old detail was `(stderr or stdout)[:2000]`, and on a CLI that prints
    its whole message stream that is the front of the stream — the tool list
    and the session id. The reason the run stopped is the last message, every
    time.
    """
    fake = _fake_stream(
        tmp_path,
        [
            BANNER,
            {"type": "result", "is_error": True, "subtype": "error_during_execution",
             "errors": ["the model refused to continue"], "result": ""},
        ],
        exit_code=1,
    )
    with pytest.raises(RuntimeError) as raised:
        HarnessResearcher(fake, timeout=60).gather(_task())

    said = str(raised.value)
    assert "error_during_execution" in said
    assert "the model refused to continue" in said
    # And the thing the reader actually got, which must not be back.
    assert "session_id" not in said, said[:300]
    assert "01275c13" not in said, said[:300]


def test_a_reply_that_arrives_as_a_stream_is_still_read(tmp_path):
    """The other half. A findings object at the end of an array is findings.

    Their build prints the array; this machine's prints the result object
    alone. Both are the documented `--output-format json` for their version,
    so the plane reads either rather than betting on one.
    """
    fake = _fake_stream(
        tmp_path,
        [BANNER, {"type": "assistant", "message": {"content": "working"}},
         _reply([{"title": "Chain kit", "domain": "engine", "severity": "high",
                  "quote": QUOTE, "document_text": PAGE,
                  "source_url": "https://forum.example/1"}])],
    )
    researcher = HarnessResearcher(fake, timeout=60)
    documents = researcher.gather(_task())

    assert [doc.url for doc in documents] == ["https://forum.example/1"]
    # The `result` element is also the one carrying `usage`, which is why it
    # is the element `_envelope` reaches for rather than the last one.
    assert researcher.tokens_used == 10540


def test_a_run_that_failed_still_reports_what_it_spent(tmp_path):
    """A run that died on its fourth search paid for three.

    Metered before the raise, or the plane's cost column tells the reader
    their failed runs were free.
    """
    fake = _fake_stream(
        tmp_path,
        [BANNER, {"type": "result", "is_error": True, "subtype": "error_max_turns",
                  "usage": {"input_tokens": 900, "output_tokens": 100},
                  "total_cost_usd": 0.42}],
        exit_code=1,
    )
    researcher = HarnessResearcher(fake, timeout=60)
    with pytest.raises(RuntimeError, match="error_max_turns"):
        researcher.gather(_task())

    assert researcher.tokens_used == 1000
    assert researcher.cost_usd == 0.42


def test_a_cli_that_prints_nothing_at_all_still_says_something(tmp_path):
    """`no output` beats an empty string after a colon."""
    fake = _fake_stream(tmp_path, [], exit_code=2)
    with pytest.raises(RuntimeError, match="exited 2"):
        HarnessResearcher(fake, timeout=60).gather(_task())


def test_a_failure_kriko_recognises_names_the_next_action(tmp_path):
    """A reason without an action is half an answer.

    "exited 1: usage limit reached" tells a reader what happened and not
    whether to wait, log in, or report it -- and this button has now failed on
    them in two releases.
    """
    fake = _fake_stream(
        tmp_path,
        [BANNER, {"type": "result", "is_error": True, "subtype": "error",
                  "errors": ["Claude usage limit reached, resets 3pm"]}],
        exit_code=1,
    )
    with pytest.raises(RuntimeError) as raised:
        HarnessResearcher(fake, timeout=60).gather(_task())

    said = str(raised.value)
    assert "usage limit reached" in said
    assert "no headroom" in said


def test_a_failure_we_do_not_recognise_is_reported_without_a_guess(tmp_path):
    """No hint beats a wrong hint. The CLI's own words still get through."""
    fake = _fake_stream(
        tmp_path,
        [BANNER, {"type": "result", "is_error": True,
                  "errors": ["the tessellator declined"]}],
        exit_code=1,
    )
    with pytest.raises(RuntimeError) as raised:
        HarnessResearcher(fake, timeout=60).gather(_task())

    said = str(raised.value)
    assert "the tessellator declined" in said
    assert " -- " not in said.split("exited 1: ", 1)[1]


def test_every_recognised_failure_class_has_an_action_in_it():
    """The table is the mechanism; this is the gate on adding to it.

    A hint that only restates the error would be worse than none -- it costs
    the reader a sentence and gives them nothing -- so each one has to name
    something to do or somewhere to send it.
    """
    for needles, hint in harness_mod.HINTS:
        assert needles and all(needle == needle.lower() for needle in needles)
        assert any(
            word in hint.lower()
            for word in ("run", "wait", "switch", "press", "send", "reinstall",
                         "check", "cannot pay")
        ), hint


def test_the_spawn_asks_for_the_readers_own_configuration_to_be_left_out(
    monkeypatch,
):
    """`--strict-mcp-config` and `--safe-mode`, where the CLI has them.

    The reader's init banner named their own failed `kriko` MCP server, so
    passing no `--mcp-config` was never the same as running with no MCP
    servers — and the same door hands over their `CLAUDE.md`, hooks, skills
    and output style, none of which were written for a prompt whose contract
    is one JSON object.
    """
    one = next(h for h in harness_mod.KNOWN if h.id == "claude-code")
    assert one.preferred == ("--strict-mcp-config", "--safe-mode")

    monkeypatch.setitem(
        harness_mod._DECLARED, one.executable,
        frozenset({"--strict-mcp-config", "--safe-mode", "--output-format"}),
    )
    assert harness_mod.command_for(one)[-2:] == [
        "--strict-mcp-config", "--safe-mode"]


def test_a_flag_this_machines_cli_never_heard_of_is_not_passed(monkeypatch):
    """Hygiene must not cost a reader the plane.

    The defect report came from `claude_code_version 2.1.261` and this machine
    is on another; versions are not ordered the way flag support is. So the
    vector is built from the CLI's own `--help` and an older build simply gets
    the base vector, which still runs.
    """
    one = next(h for h in harness_mod.KNOWN if h.id == "claude-code")
    # Keyed by the *resolved* path: `locate` is what `command_for` actually
    # runs, because a reader whose PATH does not carry `claude` still has one
    # on disk and a bare name would not start it.
    found = harness_mod.locate(one) or one.executable
    monkeypatch.setitem(harness_mod._DECLARED, found, frozenset())

    assert harness_mod.command_for(one) == [found, *one.args]


def test_asking_what_the_cli_declares_never_raises(monkeypatch):
    """A `--help` that cannot run is "declares nothing extra", not a failure.

    `_run` already answers a missing CLI with `NoHarness`; a feature probe
    that raised something else on the way there would replace a sentence a
    reader can act on with a stack trace.
    """
    harness_mod._DECLARED.pop("kriko-no-such-command-exists", None)
    assert harness_mod.declared("kriko-no-such-command-exists") == frozenset()


def test_a_missing_executable_says_so_rather_than_raising_oserror():
    fake = harness_mod.Harness("nope", "Nope", "kriko-no-such-command-exists")
    with pytest.raises(NoHarness):
        HarnessResearcher(fake, timeout=5).gather(_task())


def test_the_findings_object_survives_a_missing_fence():
    """A model that forgets the backticks has still done the research.

    Losing a completed run to a formatting slip would be the worst kind of
    fragility — expensive to reproduce, and invisible until it happens.
    """
    assert _payload('```json\n{"findings": []}\n```') == {"findings": []}
    assert _payload('Sure.\n{"findings": [{"title": "x"}]}') == {
        "findings": [{"title": "x"}]
    }
    assert _payload("nothing at all") == {}
    assert _payload("") == {}


def test_the_brief_the_plane_sends_is_the_brief_a_reader_would_paste():
    """Two planes, one protocol.

    `HarnessResearcher` inherits `brief()` and appends only the reporting step.
    If it built its own brief the two free planes would drift into two
    protocols, and the pack's principle would be quoted into one of them.
    """
    from kriko.research.agent import AgentResearcher

    task = _task(value_principle="Keep only what an inspection would not catch.")
    assert HarnessResearcher.brief is AgentResearcher.brief
    body = HarnessResearcher(harness_mod.KNOWN[0]).brief(task)
    assert "Keep only what an inspection would not catch." in body


def test_the_factory_refuses_rather_than_returning_a_broken_plane(monkeypatch):
    """`MissingKey`'s sibling. "No agent installed" is a screen, not a run."""
    from app import providers

    monkeypatch.setattr(harness_mod, "available", lambda: [])
    with pytest.raises(NoHarness) as raised:
        providers.harness_researcher()
    # The names, so the message is actionable.
    for one in harness_mod.KNOWN:
        assert one.executable in str(raised.value)


def test_the_plane_is_reachable_from_a_research_request(monkeypatch, tmp_path):
    """The wiring, which is the half that was missing.

    `_researcher` special-cased `api` and delegated everything else to
    `get_researcher`, which knows only `agent|api`. `harness` had to be added
    beside `api` rather than inside the engine: `kriko/` owns no subprocesses
    any more than it owns sockets.
    """
    from kriko.research import get_researcher

    with pytest.raises(ValueError, match="agent\\|api"):
        get_researcher({"backend": "harness"})

    seen = {}
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kwargs: seen.update(kwargs) or "the plane",
    )
    assert tasks._researcher({"backend": "harness", "harness": "opencode"}) == "the plane"
    assert seen["preferred"] == "opencode"


# ── B93: the run that finds nothing ──────────────────────────────────────────


def test_every_plane_has_a_sentence_for_a_run_that_found_nothing():
    """Keyed by plane so a fifth plane cannot be added without one.

    The three that exist are the three shapes of empty run, and each has a
    different next action: hand the brief over, accept a coverage answer, or
    check a key.
    """
    from app.providers.harness import HarnessResearcher as H
    from kriko.research import AgentResearcher, ApiResearcher

    for cls in (AgentResearcher, ApiResearcher, H):
        assert cls.name in tasks.EMPTY_RUN
        assert len(tasks.EMPTY_RUN[cls.name]) > 60


def test_the_empty_run_note_names_the_next_action():
    class _Plane:
        name = "agent"

    note = tasks._empty_run_note(_Plane())
    assert "brief" in note
    # The reader's next click, by name. A note that explains the design
    # without saying where to go is the 0.5.3 log with more words in it.
    assert "Run my agent on this" in note or "Connect" in note


def test_a_plane_that_says_why_has_its_own_reason_kept():
    class _Plane:
        name = "harness"
        note = "the harness answered without a findings list"

    note = tasks._empty_run_note(_Plane())
    assert note.startswith("the harness answered without a findings list")
    assert tasks.EMPTY_RUN["harness"] in note


def test_an_unknown_plane_still_gets_a_sentence():
    """Fails open. A plane with no entry must not produce an empty log line."""
    class _Plane:
        name = "experimental"

    assert "experimental" in tasks._empty_run_note(_Plane())


@pytest.mark.parametrize(
    "documents,verdicts,expected",
    [
        (0, {}, "brief ready"),
        (2, {"accepted": [1], "rejected": []}, "1 claim(s) kept"),
        (2, {"accepted": [1], "rejected": [1, 1]}, "2 refused"),
        (2, {"accepted": [], "rejected": [1, 1]}, "all 2 finding(s) refused"),
        (2, {"accepted": [], "rejected": []}, "none of them said anything keepable"),
    ],
)
def test_the_outcome_line_distinguishes_the_ways_a_run_ends(
    documents, verdicts, expected
):
    """`0 claim(s) kept` was true for four different runs and useful for none."""
    class _Plane:
        name = "agent"

    assert expected in tasks._outcome(_Plane(), documents, verdicts)


# ── the absent gate B92 names ────────────────────────────────────────────────


def _settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


def _seed(tmp_path):
    conn = connect(tmp_path / "k.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Thing s1')"
    )
    conn.commit()
    conn.close()


class _Recorder:
    def __init__(self):
        self.job_id = "job-1"
        self.lines: list[str] = []

    def set(self, fraction, message=""):
        if message:
            self.lines.append(message)

    def log(self, message):
        self.lines.append(message)

    def check(self):
        pass

    @property
    def log_text(self) -> str:
        return "\n".join(self.lines)


def test_a_run_that_succeeds_kept_something_refused_something_or_said_why(tmp_path):
    """The gate B92 names, on the plane that gathers nothing.

    This is the assertion whose absence let 0.5.3 ship: every automated check
    passed on a research run that produced a `succeeded` row, an empty log and
    no claim. A run is allowed to keep nothing — two of three planes never
    fetch — but it is not allowed to end without saying which of those
    happened.
    """
    _seed(tmp_path)
    progress = _Recorder()
    # `agent` named rather than defaulted. It is no longer what an unnamed run
    # resolves to — that was the whole of D2, since `agent` fetches nothing —
    # but it is still what a machine with no coding-agent CLI gets, and it is
    # the plane most likely to end a run having kept nothing.
    result = tasks.research(
        _settings(tmp_path), {"subject_id": "s1", "backend": "agent"}, progress)

    text = progress.log_text
    said_why = tasks.EMPTY_RUN["agent"] in text
    kept = "kept “" in text
    refused = "refused “" in text
    assert kept or refused or said_why, text

    # And the artifact is findable afterwards, which is the other half of the
    # reader's report: the brief existed on 0.5.3 and nothing said where.
    assert "brief:" in text
    assert "Research panel" in text or "Activity" in text
    assert result["outcome"] and result["outcome"] != "0 claim(s) kept"
    assert result["note"]


def test_the_agenda_run_says_which_kind_of_nothing_it_did(tmp_path):
    """A bulk run is the first thing many readers press, and the one most
    likely to keep nothing on the free plane."""
    _seed(tmp_path)
    progress = _Recorder()
    tasks.agenda_run(
        _settings(tmp_path), {"rows": 3, "backend": "agent"}, progress)
    last = progress.lines[-1]
    assert "brief(s) ready" in last or "nothing to research" in last


def test_the_harness_plane_reaches_the_acceptance_path_the_others_use(
    tmp_path, monkeypatch
):
    """One acceptance path, whichever plane found the claim.

    The reason findings come back on stdout instead of through
    `submit_findings` is exactly this: the claim is written by
    `app/findings.py`, on this job's own thread, so the ledger, the provenance
    row and the "kept …" log line are all true at once.
    """
    _seed(tmp_path)
    fake = _fake_cli(
        tmp_path,
        _reply([{
            "title": "Timing chain kit unobtainable",
            "domain": "engine",
            "severity": "high",
            "quote": QUOTE,
            "document_text": PAGE,
            "source_url": "https://forum.example/thread/1",
            "component": "timing chain kit",
        }]),
    )
    monkeypatch.setattr(
        "app.providers.harness_researcher",
        lambda **kwargs: HarnessResearcher(fake, timeout=60),
    )
    progress = _Recorder()
    result = tasks.research(
        _settings(tmp_path), {"subject_id": "s1", "backend": "harness"}, progress
    )
    assert len(result["accepted"]) == 1, result
    assert "kept “Timing chain kit unobtainable”" in progress.log_text
    assert result["plane"] == "harness"
    assert result["outcome"] == "1 claim(s) kept"


def test_the_planes_endpoint_offers_the_third_plane(tmp_path):
    """The reader has to be able to find it. A plane nobody can press is a
    plane that does not exist — which was B90's whole lesson."""
    from fastapi.testclient import TestClient

    from app.web.app import create_app

    _seed(tmp_path)
    client = TestClient(create_app(_settings(tmp_path)))
    planes = client.get("/api/research-planes").json()["planes"]
    row = next(p for p in planes if p["id"] == "harness")
    assert row["cost_basis"] == "subscription"
    assert row["what"]
    # Named rather than counted: "no agent found" is only actionable next to
    # the commands that were looked for.
    assert row["looked_for"]
    assert row["ready"] is bool(row["harnesses"])


# ── B121: what the run is doing, while it does it ────────────────────────────
#
# "That shell supposed to show agents actions right, and the directives of
# them." It was not, and nothing was. `subprocess.run(capture_output=True)` is
# a decision to learn nothing until the process is over, so between "harness
# plane (subscription)" and the verdicts there were up to ten minutes — forty
# for a pack author — of silence, and what the agent actually did was
# invisible while it happened and gone afterwards.
#
# The gate that matters here is `test_a_line_arrives_before_the_run_is_over`:
# every other assertion below would still pass on a buffered run that narrated
# everything at the end, which is the bug wearing the fix's clothes.


def test_the_streaming_format_is_asked_for_with_the_flag_it_requires():
    """`--output-format stream-json` without `--verbose` does not start.

    The CLI refuses the combination outright ("requires --verbose"), before
    any API call — so this is the one flag in the vector that may not be
    hygiene resolved against `--help`. It is in `args` for that reason, and
    this says so in a place a future edit will trip over.
    """
    args = harness_mod.KNOWN[0].args
    assert "stream-json" in args
    assert "--verbose" in args


def _streaming_cli(tmp_path: Path, lines: list, *, wait_for: Path | None = None):
    """A CLI that prints one JSON event per line, as `stream-json` does.

    Optionally it waits for a file to appear partway through, which is how a
    test can prove the reader saw a line *before* the process ended: nothing
    creates that file except the narration callback.
    """
    script = tmp_path / f"streamer-{len(lines)}-{bool(wait_for)}.py"
    script.write_text(
        "import json, pathlib, sys, time\n"
        f"lines = {json.dumps([json.dumps(one) for one in lines])}\n"
        f"wait = {str(wait_for) if wait_for is None else repr(str(wait_for))}\n"
        "for index, line in enumerate(lines):\n"
        "    sys.stdout.write(line + '\\n')\n"
        "    sys.stdout.flush()\n"
        "    if wait and index == 0:\n"
        "        deadline = time.time() + 20\n"
        "        while time.time() < deadline and not pathlib.Path(wait).exists():\n"
        "            time.sleep(0.02)\n"
        "        if not pathlib.Path(wait).exists():\n"
        "            sys.exit(3)\n",
        encoding="utf-8",
    )
    return harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script), "-p"), structured=True
    )


def _search_event(query: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "WebSearch", "input": {"query": query}}
            ]
        },
    }


def test_a_line_arrives_before_the_run_is_over(tmp_path):
    """The whole of B121 in one assertion, and the only one that can fail on a
    buffered implementation.

    The fake CLI prints its first event and then refuses to finish until the
    narration callback has created a file. A run that reads its child's output
    only after the child exits deadlocks here and fails on the timeout, which
    is exactly the behaviour being ruled out.
    """
    sentinel = tmp_path / "the-reader-saw-it"
    one = _streaming_cli(
        tmp_path,
        [_search_event("timing chain"), _reply([])],
        wait_for=sentinel,
    )
    seen: list[str] = []

    def watching(line: str) -> None:
        seen.append(line)
        sentinel.write_text("yes", encoding="utf-8")

    researcher = HarnessResearcher(one, timeout=30)
    researcher.on_action = watching
    researcher.gather(_task())
    assert seen, "nothing was narrated at all"
    assert 'searched "timing chain"' in seen[0]


def test_what_the_agent_did_is_said_in_the_readers_words(tmp_path):
    """One line per action, and nothing for the machinery around them."""
    one = _streaming_cli(
        tmp_path,
        [
            {"type": "system", "subtype": "init", "model": "claude-x"},
            {"type": "stream_event", "event": {"delta": "ignored"}},
            _search_event("golf 1.4 tsi chain"),
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "WebFetch",
                            "input": {"url": "https://example.test/page"},
                        }
                    ]
                },
            },
            _reply([]),
        ],
    )
    seen: list[str] = []
    researcher = HarnessResearcher(one, timeout=30)
    researcher.on_action = seen.append
    researcher.gather(_task())
    said = "\n".join(seen)
    assert "claude-x" in said
    assert 'searched "golf 1.4 tsi chain"' in said
    assert "fetched https://example.test/page" in said
    assert "ignored" not in said, "a partial-token frame is not an action"
    assert researcher.actions == seen


def test_streaming_does_not_change_what_comes_back(tmp_path):
    """The reply is still the reply, and the meter still reads.

    `--output-format stream-json` ends with the same `result` object `json`
    prints alone, so a plane that narrates must parse exactly what a plane
    that did not parsed — otherwise B121 would have bought visibility with
    findings.
    """
    one = _streaming_cli(
        tmp_path,
        [
            {"type": "system", "subtype": "init", "model": "claude-x"},
            _search_event("anything"),
            _reply([
                {
                    "title": "Timing chain kit unobtainable",
                    "domain": "engine",
                    "severity": "high",
                    "quote": QUOTE,
                    "document_text": PAGE,
                    "source_url": "https://example.test/thread",
                    "component": "timing chain",
                }
            ]),
        ],
    )
    researcher = HarnessResearcher(one, timeout=30)
    documents = researcher.gather(_task())
    assert [document.url for document in documents] == ["https://example.test/thread"]
    assert researcher.extract(_task(), documents[0])[0].title == (
        "Timing chain kit unobtainable"
    )
    assert researcher.tokens_used == 1200 + 340 + 9000


def test_a_log_line_that_cannot_be_written_does_not_fail_the_run(tmp_path):
    """Narration is a nicety; the research is the job.

    A `progress.log` writing to a database that has gone away must not destroy
    a completed run of real research — so a callback that raises stops being
    called and nothing else changes.
    """
    one = _streaming_cli(tmp_path, [_search_event("anything"), _reply([])])

    def broken(line: str) -> None:
        raise RuntimeError("the log is gone")

    researcher = HarnessResearcher(one, timeout=30)
    researcher.on_action = broken
    assert researcher.gather(_task()) == []
    assert researcher.note


def test_a_cli_that_never_finishes_is_killed_and_said_so(tmp_path):
    """The ceiling still holds, now that nothing waits on `subprocess.run`."""
    script = tmp_path / "hangs.py"
    script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
    one = harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script),), structured=True
    )
    researcher = HarnessResearcher(one, timeout=1.0)
    with pytest.raises(TimeoutError) as raised:
        researcher.gather(_task())
    assert "within 1s" in str(raised.value)


def test_the_transcript_is_bounded(tmp_path, monkeypatch):
    """A CLI that will not stop talking costs a fixed amount of memory."""
    monkeypatch.setattr(harness_mod, "TRANSCRIPT_TAIL", 2048)
    script = tmp_path / "chatty.py"
    script.write_text(
        "import sys\n"
        "for _ in range(400):\n"
        "    sys.stdout.write('x' * 200 + '\\n')\n"
        "sys.stdout.write('{\"type\": \"result\", \"result\": \"done\"}\\n')\n",
        encoding="utf-8",
    )
    one = harness_mod.Harness(
        "fake", "Fake CLI", sys.executable, (str(script),), structured=True
    )
    researcher = HarnessResearcher(one, timeout=30)
    researcher.gather(_task())
    assert len(researcher.transcript) <= 2048
    # And the reply survived the bound, because the result is the last line.
    assert researcher.note


def test_narration_is_capped_and_says_that_it_stopped(tmp_path, monkeypatch):
    """An agent stuck in a tool loop cannot grow the job log without end — and
    the reader is told, because a cap that stops quietly leaves them looking at
    exactly the silence B121 fixed."""
    monkeypatch.setattr(harness_mod, "MAX_NARRATED", 5)
    one = _streaming_cli(
        tmp_path, [_search_event(f"query {index}") for index in range(40)] + [_reply([])]
    )
    seen: list[str] = []
    researcher = HarnessResearcher(one, timeout=30)
    researcher.on_action = seen.append
    researcher.gather(_task())
    assert len(seen) == 6
    assert "not shown" in seen[-1]


def test_a_cli_that_cannot_stream_still_runs(monkeypatch):
    """Visibility is the thing worth losing; the plane is not.

    The reader's CLI is not this machine's, and a build whose
    `--output-format` never listed `stream-json` would refuse the streaming
    vector outright — the same dead plane, with the same "Claude Code exited
    1", that took two releases to get out of. So the format is chosen against
    what `--help` actually lists."""
    one = harness_mod.KNOWN[0]
    monkeypatch.setattr(harness_mod, "locate", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(harness_mod, "declared", lambda _: frozenset())
    monkeypatch.setattr(
        harness_mod, "helptext",
        lambda _: "--output-format <format>  (choices: \"text\", \"json\")",
    )
    vector = harness_mod.command_for(one)
    assert "stream-json" not in vector
    assert "json" in vector
    assert "--allowedTools" in vector, "the grant is not optional"

    monkeypatch.setattr(
        harness_mod, "helptext",
        lambda _: "--output-format <format>  (choices: \"json\", \"stream-json\")",
    )
    assert "stream-json" in harness_mod.command_for(one)
