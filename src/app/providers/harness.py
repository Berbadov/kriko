"""The third plane: drive the coding agent the reader already pays for.

`AgentResearcher` writes a brief and stops, because *something else* is
supposed to read it. For a reader in the terminal that something is their own
harness. For a reader who double-clicked an installer it was nobody at all:
`app/agentconfig.py` teaches a harness how to call Kriko, and nothing anywhere
called a harness. So pressing **Research** rendered a brief, gathered zero
documents and reported `succeeded / 0 claim(s) kept` — which is the reader's
"research does nothing, it says done but the logs return nothing", exactly.

This closes the loop in the direction that was missing. `claude -p` (and
`opencode run`) are complete headless research loops: a model that can search,
on a subscription that is already paid for, driven from a prompt and answering
on stdout. Marginal cost stays zero because it is the reader's own plan.

Three decisions are load-bearing:

* **The spawned agent gets no MCP config, and no write tools.** It could have
  been handed Kriko's own `submit_findings` — but then claims would arrive by
  one door while the job that started it reported nothing, and `tasks.py`'s
  own "kept …" / "refused …" lines would still never be written. Instead the
  findings come back *on stdout*, become `Document`s here, and flow through
  `_research`'s ordinary acceptance path. One acceptance path, one ledger, one
  set of log lines that are true: a claim's provenance must not depend on
  which door it came in.

  **Passing no `--mcp-config` turned out not to mean "no MCP servers".** The
  reader's pack-authoring run failed and its init banner said
  `"mcp_servers":[{"name":"kriko","status":"failed"}]` — their own global
  configuration, loaded because the working directory is their home. The same
  door hands over their `CLAUDE.md`, their hooks, their output style and their
  skills, none of which were written for a prompt whose whole contract is
  "print one JSON object and nothing after it". So the vector now asks for
  `--strict-mcp-config` and `--safe-mode` where the installed CLI declares
  them (`command_for`), which is what "sandboxed spawn" was always supposed
  to mean.
* **`--allowedTools` is an explicit allowlist, never a denylist.** Handing a
  coding agent `Bash` to research a car is a remote-code path with extra
  steps. `SEARCH_TOOLS` is the whole grant, and it is search and fetch.
* **This lives in `app/`, not `kriko/`.** The engine owns no sockets and no
  subprocesses, which is the same reason `app/providers/` exists for the paid
  plane's HTTP.

What the CLI answers with also carries `usage` and `total_cost_usd`, which is
how this plane reports tokens the other two cannot — stamped on the instance
for `tasks.py` to read duck-typed, exactly as `api_researcher` stamps `model`.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kriko.research.agent import AgentResearcher
from kriko.research.base import Document, Finding, ResearchTask

#: Everything the spawned agent is allowed to do. Read the module docstring
#: before adding to this: a research plane that can write files or run shell
#: commands is not a research plane.
SEARCH_TOOLS = ("WebSearch", "WebFetch")

#: How long one subject's research may take before the run is abandoned. A
#: headless agent doing three searches and reading four pages lands well
#: inside this; the ceiling exists so a hung CLI fails a job rather than
#: holding the single job worker forever.
TIMEOUT_SECONDS = 600.0

#: And how long *authoring a whole pack* may take, which is not the same job.
#: One subject's research is three searches; a pack is a category read from
#: scratch, four decisions made from what was read, and two or three subjects
#: researched before a single line is printed. Measured here against the real
#: CLI, `packauthor.brief` runs past ten minutes without being stuck, so the
#: research ceiling would have killed a healthy run and called it a hang.
AUTHOR_TIMEOUT_SECONDS = 2400.0


class NoHarness(RuntimeError):
    """The harness plane was asked for and no harness CLI is on this machine."""


@dataclass(frozen=True)
class Harness:
    """One coding-agent CLI, and how to run it non-interactively.

    A closed vocabulary — CLIs are a fixed engineering category, not data that
    grows with pack coverage, so the scalability rule against hand-enumerated
    lists does not apply here. What *would* apply is enumerating car makes in
    the prompt, which is why the prompt is the pack's brief and nothing else.
    """

    id: str
    label: str
    executable: str
    #: Argument vector. The prompt is **not** in it — see `_run`.
    args: tuple[str, ...] = ()
    #: True when the CLI answers with one JSON object carrying `result` and
    #: `usage`. A CLI that only prints prose still works — it just cannot
    #: report what it spent, and the metered columns stay NULL rather than
    #: being filled with a guess.
    structured: bool = True
    env: dict = field(default_factory=dict)
    #: What to run instead of `args` when this machine's CLI does not list
    #: `needs_in_help` among the things it can do. The streaming vector is the
    #: one this plane wants (see `_claude_args`); this is the one that still
    #: works on a build that has never heard of it. Empty means there is no
    #: fallback and `args` is the only vector.
    plain_args: tuple[str, ...] = ()
    #: The word that must appear in `--help` for `args` to be usable at all.
    #: Not an option name — `declared` already covers those — but a *value*,
    #: which is the part of a CLI's contract that has no flag to probe.
    needs_in_help: str = ""
    #: Flags to add **only if this machine's CLI declares them**. Hygiene
    #: rather than function: a reader on an older build must not lose the
    #: plane over a flag their `claude` has never heard of, and `--help` is
    #: the only honest way to ask. Resolved by `command_for`.
    preferred: tuple[str, ...] = ()
    #: Why this CLI cannot be used, if it cannot. Non-empty means `available()`
    #: will not offer it, while `/api/research-planes` still reports that it
    #: was found — "your opencode is installed and Kriko will not use it, and
    #: here is why" is an answer; silently ignoring it is not.
    unusable: str = ""
    #: True when the prompt may be handed over as an argument after `--`.
    #:
    #: **This is the reader's "no stdin data received in 3s".** Stdin was
    #: chosen (B92) because `--allowedTools` is variadic and swallowed a
    #: trailing prompt — but `--` ends option parsing, which solves the same
    #: problem without a pipe. And a pipe is the part that turned out to be
    #: fragile on Windows: the CLI is often a `claude.cmd` shim, so the handle
    #: crosses `cmd.exe` into node, and when it does not arrive the CLI waits
    #: three seconds and then runs *with no prompt at all* — which is exactly
    #: the failure the reader pasted, on a run that had worked minutes before.
    #: An argument cannot be lost in transit.
    prompt_argument: bool = True
    #: Where this CLI installs itself, relative to the reader's home, for when
    #: `PATH` does not carry it. See `locate`.
    homes: tuple[str, ...] = (
        ".local/bin",
        "AppData/Local/Programs",
        "AppData/Roaming/npm",
        ".npm-global/bin",
        "node_modules/.bin",
        "bin",
    )


def _claude_args() -> tuple[str, ...]:
    """Headless, streaming, and allowed to search and nothing else.

    **`stream-json` rather than `json`, since B121.** Under `json` the CLI
    prints one object when it is finished, so a ten-minute run says nothing
    for ten minutes and the reader watching the job log cannot tell a run that
    is searching from one that is hung. `stream-json` prints one JSON object
    per event as it happens — the tool calls, the pages fetched, the model's
    own narration — which `narrate` turns into the lines the log shows. The
    reply is unchanged: the last event is the same `result` object, carrying
    the same `result`, `usage` and `total_cost_usd`, and `_envelope` already
    read line-delimited output.

    `--verbose` is not decoration: `claude -p --output-format stream-json`
    refuses to start without it ("requires --verbose"), before any API call.
    It is in `args` rather than in `preferred` for exactly that reason — a
    machine whose CLI does not take it has no working vector here anyway, and
    a silently dropped flag would turn a hard error into a mystery.
    """
    return (
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--allowedTools", ",".join(SEARCH_TOOLS),
    )


#: In preference order. The first *usable* one found on PATH is the one used,
#: and `/api/research-planes` reports which.
KNOWN = (
    Harness(
        "claude-code",
        "Claude Code",
        "claude",
        _claude_args(),
        # `--strict-mcp-config` with no `--mcp-config` is zero MCP servers;
        # `--safe-mode` drops the rest of the reader's configuration — their
        # `CLAUDE.md`, hooks, skills, plugins, output style — while leaving
        # auth, the built-in tools and permissions alone. Both are what this
        # spawn already claimed to be.
        preferred=("--strict-mcp-config", "--safe-mode"),
        # The reader's Windows CLI is not this machine's. A build whose
        # `--output-format` never listed `stream-json` would refuse the
        # streaming vector outright and the plane would be dead again, with
        # the same "Claude Code exited 1" it took two releases to get out of.
        # So: watch the run where the CLI can stream, and fall back to the
        # single-object reply where it cannot. Visibility is the thing worth
        # losing; the plane is not.
        needs_in_help="stream-json",
        plain_args=(
            "-p",
            "--output-format", "json",
            "--allowedTools", ",".join(SEARCH_TOOLS),
        ),
    ),
    Harness(
        "opencode",
        "opencode",
        "opencode",
        ("run", "--agent", "kriko-harness"),
        structured=False,
    ),
)

_OPENCODE_AGENT_PATH = Path.home() / ".opencode" / "agents" / "kriko-harness.md"

_OPENCODE_AGENT_BODY = """---
description: Kriko harness research: search and fetch only
mode: subagent
permission:
  bash: deny
  edit: deny
  webfetch: allow
  websearch: allow
---

Research the subject in the prompt below and report findings as instructed.
"""


def _ensure_opencode_agent() -> None:
    if not _OPENCODE_AGENT_PATH.exists():
        _OPENCODE_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OPENCODE_AGENT_PATH.write_text(_OPENCODE_AGENT_BODY, encoding="utf-8")


#: Extra directories to search, `os.pathsep`-separated. The escape hatch for a
#: reader whose CLI is somewhere none of the rules below predict — one
#: environment variable beats a support thread.
DIRS_ENV = "KRIKO_HARNESS_DIRS"

#: Executable suffixes to try on Windows, where `claude` is `claude.exe` and an
#: npm-installed one is `claude.cmd`. Empty string first: a bare name is right
#: everywhere else, and on Windows `shutil.which` has already handled PATHEXT.
_SUFFIXES = (("", ".exe", ".cmd", ".bat") if os.name == "nt" else ("",))


def locate(one: Harness) -> str:
    """The full path to this CLI, or `""`.

    **`PATH` is not enough, and that is not a theory.** The sidecar is launched
    by a desktop shell, which is launched by the OS's file manager, which hands
    down the `PATH` that existed *at login*. A reader who installs Claude Code
    and comes straight back to Kriko has a `claude.exe` on disk
    (`%USERPROFILE%/.local/bin` is where its own installer puts it) and a
    `shutil.which("claude")` that returns `None` — so `available()` is empty,
    the harness plane reports itself not ready, and every agent operation in
    the app quietly does nothing. Nothing in the UI can say why, because
    nothing in the app knows there is anything to say.

    So: `PATH` first (it is right whenever it is populated), then `DIRS_ENV`,
    then the handful of directories these CLIs actually install themselves
    into. That list is allowed to be a constant for the same reason `KNOWN` is
    — coding-agent CLIs are a closed engineering category, not data that grows
    with pack coverage — and it is a *fallback*, so a wrong guess in it costs
    nothing.
    """
    found = shutil.which(one.executable)
    if found:
        return found
    home = Path.home()
    roots = [Path(d) for d in os.environ.get(DIRS_ENV, "").split(os.pathsep) if d]
    roots += [home / part for part in one.homes]
    for root in roots:
        for suffix in _SUFFIXES:
            candidate = root / f"{one.executable}{suffix}"
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            except OSError:
                continue
    return ""


def available() -> list[Harness]:
    """Which harness CLIs this machine can actually start *and* sandbox."""
    return [h for h in KNOWN if not h.unusable and locate(h)]


def found_but_unusable() -> list[Harness]:
    """Installed, and deliberately not driven. For the screen to explain."""
    return [h for h in KNOWN if h.unusable and locate(h)]


def chosen(preferred: str = "") -> Harness | None:
    found = available()
    if preferred:
        return next((h for h in found if h.id == preferred), None)
    return found[0] if found else None


#: One `--help` per executable per process. Cached because `_run` is called
#: once per subject in an agenda run and spawning a second process to ask a
#: question whose answer cannot change mid-run is waste.
_DECLARED: dict[str, frozenset[str]] = {}
_HELP: dict[str, str] = {}

_OPTION = re.compile(r"--[a-z][a-z0-9-]+")


def helptext(executable: str) -> str:
    """What `--help` printed, cached. `""` on any failure.

    The raw text as well as the option names, because not every capability is
    an option: `--output-format` exists on every build of the CLI and the
    *values* it accepts are what changed. A vector that asks for a format this
    machine's CLI does not list is a plane that cannot start, which is B92's
    failure with a different flag.
    """
    if executable in _HELP:
        return _HELP[executable]
    try:
        done = subprocess.run(  # noqa: S603 - fixed executable, no shell
            [executable, "--help"], capture_output=True, text=True, timeout=30
        )
        text = (done.stdout or "") + (done.stderr or "")
    except Exception:  # noqa: BLE001 — see `declared`
        text = ""
    _HELP[executable] = text
    _DECLARED[executable] = frozenset(_OPTION.findall(text))
    return text


def declared(executable: str) -> frozenset[str]:
    """Every long option this machine's copy of `executable` declares.

    Feature detection rather than a version check: the reader is on
    `claude_code_version 2.1.261` and this machine is not, versions are not
    ordered the way flag support is, and `--help` is the CLI's own answer.

    An empty set on any failure, which reads as "declares nothing extra" and
    costs the reader nothing but the hygiene flags — a missing CLI is already
    `NoHarness`, and a `--help` that hangs must not become a plane that hangs.
    """
    if executable not in _DECLARED:
        helptext(executable)
    return _DECLARED.get(executable, frozenset())


def command_for(one: Harness) -> list[str]:
    """The vector this machine will actually run — `args` plus what it takes.

    A function rather than a line inside `_run` because the gate that matters
    runs the *real* CLI against it: every earlier check here asserted the
    shape of `args` and none asserted the CLI would accept them, which is how
    B92 shipped a plane that could not start at all. A test can only judge the
    vector if the vector has a name.
    """
    executable = locate(one) or one.executable
    supported = declared(executable)
    args = one.args
    if one.needs_in_help and one.plain_args:
        if one.needs_in_help not in helptext(executable):
            args = one.plain_args
    return [executable, *args, *(f for f in one.preferred if f in supported)]


# ── The output contract ──────────────────────────────────────────────────────

#: Appended to the pack's brief. The brief already says what to look for and
#: what is worth keeping — it is written for an agent holding Kriko's MCP
#: tools, so the only thing it needs replacing is the *reporting* step.
CONTRACT = """
## How to report findings (this run)

You have no Kriko tools in this session. Do not attempt to call
`submit_findings`; there is nothing to call. Instead, print your findings as
one JSON object as the last thing you say, in a ```json fence:

```json
{"queries": ["the searches you actually ran"],
 "findings": [
  {"title": "...", "domain": "...", "severity": "high|medium|low",
   "quote": "verbatim sentence from the page",
   "document_text": "a paragraph or two of the page, containing that quote",
   "source_url": "https://...",
   "component": "the concrete part", "body": "...", "advice": "...",
   "stance": "supports|disputes"}
]}
```

`quote` must appear verbatim inside `document_text` — it is checked, and a
finding whose quote cannot be found is refused rather than trusted. Paste the
text you actually read; never reconstruct it from memory.

The searches above are the pack's seeds, not a script. Adapt them to this
subject and to the market its terms are written in, run the ones that are
worth running, and say in `body` which query a finding came from. If a search
returns nothing usable, that is a finding worth reporting as one — an invented
claim outlives you in the pack.

List every search you ran in `queries`, in the words you actually typed —
including the ones that returned nothing. That list is how a pack learns which
seed shapes earn their place; it has no effect on whether a finding is kept, so
there is nothing to gain by editing it after the fact.

If you found nothing at all, print `{"findings": []}`. Print nothing after the
fence.
"""

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _payload(text: str) -> dict:
    """The findings object, from whatever the agent wrapped it in.

    Fence first, then the last balanced brace run, because a model that was
    told to print a fence usually does and sometimes does not, and losing a
    completed run of real research to a missing backtick would be absurd.
    """
    text = text or ""
    for match in reversed(_FENCE.findall(text)):
        try:
            parsed = json.loads(match)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    start = text.find("{")
    while start != -1:
        try:
            parsed = json.loads(text[start:])
        except ValueError:
            start = text.find("{", start + 1)
            continue
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _tokens(usage) -> int:
    """Every token the reply admits to, cache reads included.

    Cache reads are cheaper, not free, and this number is reported as *usage*
    rather than as cost — the CLI reports the cost itself and that is the
    number the ledger charges.
    """
    if not isinstance(usage, dict):
        return 0
    return sum(
        _int(usage.get(key))
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )


def _envelope(stdout: str) -> dict:
    """The CLI's result object, out of any of the three shapes it prints.

    B105. The reader's failure arrived as a JSON *array* — `[{"type":
    "system","subtype":"init",...}, ...]` — because their build of the CLI
    prints the whole message stream under `--output-format json` while this
    machine's prints the result object alone. Both are the documented format
    for their version, so this reads either, plus the line-delimited form a
    CLI that streams would emit:

    1. one object — take it;
    2. an array of stream messages — take the last `result` (an array whose
       last element is an assistant turn is still a stream, and the `result`
       is the element that carries `usage`, `total_cost_usd` and `is_error`);
    3. one object per line — the last parseable one, as before.

    `{}` when there is no object at all, which the callers read as "this CLI
    answered in prose" rather than as an error: the findings fence may still
    be in it.
    """
    text = (stdout or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        objects = [item for item in parsed if isinstance(item, dict)]
        results = [item for item in objects if item.get("type") == "result"]
        if results:
            return results[-1]
        return objects[-1] if objects else {}
    last = {}
    for line in reversed(text.splitlines()):
        try:
            one = json.loads(line)
        except ValueError:
            continue
        if not isinstance(one, dict):
            continue
        # The `result` event by preference, not merely the last object: under
        # `--output-format stream-json` the result is followed by nothing
        # today and by whatever a future CLI adds tomorrow, and it is the one
        # event carrying `result`, `usage`, `total_cost_usd` and `is_error`.
        if one.get("type") == "result":
            return one
        last = last or one
    return last


def _why(envelope: dict, stdout: str, stderr: str) -> str:
    """Why the run failed, in the words the CLI used.

    The reader's report was a wall of init banner: the old detail was
    `(stderr or stdout)[:2000]`, and 2000 characters from the *front* of a
    stream is the tool list, the session id and the model — everything except
    the reason. The reason is in the last message, so this reads the envelope
    first and falls back to the *tail*.

    Ordered so the most specific thing comes first: the CLI's own `subtype`
    (`error_max_turns`, `error_during_execution`), then whatever it put in
    `errors`, then the text it managed to produce, then stderr.
    """
    parts: list[str] = []
    subtype = envelope.get("subtype")
    if isinstance(subtype, str) and subtype.strip() and subtype != "success":
        parts.append(subtype.strip())
    errors = envelope.get("errors")
    if isinstance(errors, list):
        parts.extend(str(one).strip() for one in errors if str(one).strip())
    for key in ("error", "api_error_status", "result"):
        value = envelope.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
            break
    said = (stderr or "").strip()
    if said:
        parts.append(said[-800:])
    if not parts:
        tail = (stdout or "").strip()
        if tail:
            parts.append("its last 800 characters were: " + tail[-800:])
    # Deduplicated in order: `subtype` and `errors[0]` are often the same
    # sentence twice, and a reader reading a defect report should not have to
    # wonder whether that means two things went wrong.
    return " -- ".join(dict.fromkeys(parts))[:2000] or "no output"


# ── what the run is doing, while it does it ──────────────────────────────────

#: The longest prompt that goes on the command line rather than through a
#: pipe. Windows caps a process's whole command line at 32,767 characters and
#: the vector itself takes some of that, so this leaves a wide margin — a
#: research brief is a few thousand characters and a pack-authoring brief is
#: under ten thousand. Past it, stdin is the only option and its risk (see
#: `_run`) is accepted because the alternative is not running at all.
MAX_PROMPT_ARGUMENT = 24000

#: How much of a run's raw output is kept in memory. The reply is parsed from
#: this, so it has to hold the last `result` event — which is the last line —
#: and it is bounded for the reason `termpty.SCROLLBACK` is: a process that
#: will not stop talking must cost a fixed amount of memory, not all of it.
TRANSCRIPT_TAIL = 512 * 1024

#: The most lines one run may narrate. A ceiling rather than a rate limit: the
#: job log is a column in `app.sqlite` that every reader of the job re-reads,
#: and an agent stuck in a tool loop must not be able to grow it without end.
#: A real research run narrates a few dozen.
MAX_NARRATED = 400

#: Events that are machinery rather than actions — session bookkeeping, the
#: partial-token frames, the command list. Named rather than filtered by
#: "anything I do not recognise", so a *new* event type shows up as a line
#: nobody wrote a translation for instead of silently disappearing.
QUIET_EVENTS = frozenset(
    {"stream_event", "active_goal", "autocompact_state", "rate_limit_event"}
)


def _short(text: str, limit: int = 160) -> str:
    """One line, trimmed. A log line that wraps four times is not a log line."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _tool_line(name: str, args: dict) -> str:
    """What one tool call was, in the reader's words rather than the API's.

    `SEARCH_TOOLS` is the whole grant, so there are two shapes worth naming
    and a general one for anything a future grant adds. It reads the argument
    the tool is *about* — the query, the URL — because "WebSearch" on its own
    tells a reader watching the log nothing they did not already assume.
    """
    args = args if isinstance(args, dict) else {}
    query = args.get("query") or args.get("q")
    url = args.get("url")
    if name == "WebSearch" and query:
        return f'searched "{_short(query, 120)}"'
    if name == "WebFetch" and url:
        return f"fetched {_short(url, 120)}"
    detail = query or url or ""
    return f"{name} {_short(detail, 100)}".strip()


def narrate(event: dict) -> str:
    """One stream event, as a line for the job log — or `""` for machinery.

    This is the whole of B121's answer to *"that shell is supposed to show the
    agent's actions"*. It was not, and nothing was: between "harness plane" and
    the verdicts there were up to ten minutes of silence, and what the agent
    actually did was invisible while it happened and gone afterwards. The
    transport is the job log, which already streams to both the app and
    `kriko tui` — a run's actions do not need a second channel, they needed a
    sender.
    """
    if not isinstance(event, dict):
        return ""
    kind = event.get("type")
    if kind in QUIET_EVENTS:
        return ""
    if kind == "system":
        if event.get("subtype") != "init":
            return ""
        model = str(event.get("model") or "").strip()
        return f"started {model}".strip() if model else "started"
    if kind == "assistant":
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        lines = []
        for block in blocks if isinstance(blocks, list) else ():
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                lines.append(_tool_line(str(block.get("name") or ""), block.get("input")))
            elif block.get("type") == "text" and str(block.get("text") or "").strip():
                lines.append(_short(block["text"]))
        return "; ".join(one for one in lines if one)
    if kind == "user":
        # Only the failures. A tool result is the page the agent just read,
        # and repeating it into the log would bury the run in its own sources
        # — but a search that errored is the thing a reader most needs to see.
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        for block in blocks if isinstance(blocks, list) else ():
            if isinstance(block, dict) and block.get("is_error"):
                return "a tool call failed: " + _short(str(block.get("content") or ""), 120)
        return ""
    if kind == "result":
        turns = event.get("num_turns")
        cost = event.get("total_cost_usd")
        said = "finished"
        if isinstance(turns, int):
            said += f" after {turns} turn(s)"
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost:
            said += f", ${cost:.4f} on the subscription's account"
        return said
    return ""


#: What a harness failure means, and what to do about it. A closed
#: vocabulary of *CLI* failure classes — a fixed engineering category, like
#: `KNOWN` itself, and nothing that grows with pack coverage. Matched against
#: the reason `_why` extracted, lowercased, first hit wins.
HINTS = (
    (("usage limit", "rate limit", "limit reached", "quota"),
     "your Claude subscription has no headroom right now. Wait for the reset "
     "the message names, or switch to another plane on the Agents screen."),
    (("not logged in", "please run /login", "unauthorized", "authentication",
      "invalid api key", "oauth"),
     "the CLI is not logged in, and only you can log it in -- no API call can "
     "do it on its behalf. Open the terminal in this app (Ctrl+`), run "
     "`claude`, and follow the login prompt (or type `/login`). Then press "
     "this again. Kriko Console in your Start menu opens the same shell "
     "without the app."),
    (("credit balance", "billing", "payment"),
     "the account behind the CLI cannot pay for this run."),
    (("error_max_turns",),
     "the agent ran out of turns before it reported. This is Kriko's to fix, "
     "not yours -- please send the log."),
    (("enoent", "not recognized", "cannot find the path"),
     "the CLI could not start. Check that `claude` runs in the terminal in "
     "this app; if it is installed somewhere unusual, set KRIKO_HARNESS_DIRS "
     "to its folder. The Agents screen names the binary Kriko found."),
)


def _hint(reason: str) -> str:
    """The next action for a failure class Kriko recognises, or nothing.

    A reason with no action attached is only half of what a reader needs.
    `Claude Code exited 1: error_during_execution` says what happened; it
    does not say whether to wait, log in, or report it — and a reader who has
    now watched this button fail in two releases has earned the second half.
    """
    low = (reason or "").lower()
    for needles, hint in HINTS:
        if any(needle in low for needle in needles):
            return hint
    return ""


class HarnessResearcher(AgentResearcher):
    """Research by *running* the harness, rather than by writing to it.

    Inherits `brief()` unchanged and on purpose: the brief an agent is handed
    here must be the same document a reader pastes into their own terminal, or
    the two planes would drift into two protocols. Only the reporting step is
    replaced, by appending `CONTRACT`.
    """

    name = "harness"
    cost_basis = "subscription"

    def __init__(self, harness: Harness, *, timeout: float = TIMEOUT_SECONDS):
        self.harness = harness
        self.timeout = timeout
        #: Read duck-typed by `app/web/tasks.py`. `None` until a run happens,
        #: which is the difference between "spent nothing" and "cannot count".
        self.tokens_used: int | None = None
        self.cost_usd: float | None = None
        #: Named for the provenance row, like the paid plane's `model`.
        self.model = harness.id
        self.search_provider = harness.label
        #: Findings by source url, filled by `gather` and drained by `extract`.
        self._by_url: dict[str, list[Finding]] = {}
        #: The searches the agent says it ran. Read by `app/web/tasks.py` and
        #: written to the submission row (B95) — the brief hands out seeds, so
        #: the shapes that actually get used are only knowable from here.
        self.queries_run: list[str] = []
        #: Where a line goes when the agent does something (B121). Set
        #: duck-typed by `app/web/tasks.py` to the job's own `progress.log`,
        #: exactly as `tokens_used` is read back duck-typed — the engine has
        #: no field for "somewhere to narrate to" and should not grow one.
        #: `None` means nobody is watching, which is the CLI's case and costs
        #: the run nothing.
        self.on_action: Callable[[str], None] | None = None
        #: Polled once per streamed line, the same duck-typed shape as
        #: `on_action` — `tasks.py` wires this to `Progress.check`. Raising
        #: from it is the one thing that must reach the caller unmodified:
        #: `_stream` kills the child's whole process tree and lets whatever
        #: was raised propagate as-is, so a `Cancelled` surfaces as cancelled
        #: rather than as a crash or a timeout. `None` means nobody is asking,
        #: which costs the run nothing — the CLI's own case, and every run
        #: before `pack_author`/`pack_amend`/`site_register` were given one.
        self.check_cancelled: Callable[[], None] | None = None
        #: The run's raw output, bounded. The reply is parsed out of this, and
        #: it is what a failure quotes its tail of.
        self.transcript = ""
        #: The lines this run narrated, in order. Kept so a caller that was not
        #: watching live can still ask what happened.
        self.actions: list[str] = []
        #: Why nothing came back, when nothing came back. `tasks.py` cannot
        #: read this yet; `_research`'s log gets it through the exception on
        #: the paths that are genuinely broken, and through an empty gather on
        #: the paths that merely found nothing.
        self.note = ""

    # ── gather ───────────────────────────────────────────────────────────────

    def gather(self, task: ResearchTask) -> list[Document]:
        prompt = self.brief(task) + "\n" + CONTRACT
        reply = self._run(prompt)
        payload = _payload(reply)
        reported = payload.get("queries")
        self.queries_run = [
            str(query).strip()
            for query in (reported if isinstance(reported, list) else ())
            if str(query).strip()
        ]
        raw = payload.get("findings")
        if not isinstance(raw, list):
            self.note = "the harness answered without a findings list"
            return []

        self._by_url = {}
        texts: dict[str, list[str]] = {}
        titles: dict[str, str] = {}
        for item in raw[: max(1, task.max_documents) * 8]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("source_url") or "").strip()
            quote = str(item.get("quote") or "").strip()
            if not url or not quote:
                continue
            finding = Finding(
                title=str(item.get("title") or "").strip(),
                domain=str(item.get("domain") or "").strip(),
                severity=str(item.get("severity") or "medium").strip().lower(),
                quote=quote,
                source_url=url,
                body=str(item.get("body") or ""),
                advice=str(item.get("advice") or ""),
                stance=str(item.get("stance") or "supports").strip().lower(),
                component=str(
                    item.get("component") or item.get("component_hint") or ""
                ).strip(),
            )
            if not finding.title:
                continue
            self._by_url.setdefault(url, []).append(finding)
            # The quote is appended as well as the surrounding text: the
            # grounding check reads `document.text`, and an agent that gave a
            # good quote but a careless excerpt should not have its finding
            # refused for a transcription slip it cannot see.
            page = str(item.get("document_text") or "")
            texts.setdefault(url, [])
            for part in (page, quote):
                if part and part not in texts[url]:
                    texts[url].append(part)
            titles.setdefault(url, finding.title)

        documents = [
            Document(
                url=url,
                text="\n\n".join(texts.get(url, [])),
                site_or_channel=_site(url),
                title=titles.get(url, ""),
                source_type="page",
            )
            for url in self._by_url
        ]
        if not documents:
            self.note = self.note or "the harness reported no usable findings"
        return documents

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """What `gather` already parsed, per document. No second model call."""
        return list(self._by_url.get(document.url, ()))

    def ask(self, prompt: str) -> str:
        """One prompt, one reply, for a job that is not research.

        Public because `tasks.pack_author` is a second caller with the same
        need and no interest in findings: it hands the agent a brief about a
        category and reads back a proposed pack. The plane's value is the
        *sandboxed spawn* — the allowlist, the neutral working directory, the
        absent `--mcp-config` — and that is worth reusing rather than
        reimplementing next to it.
        """
        return self._run(prompt)

    # ── the subprocess ───────────────────────────────────────────────────────

    def _run(self, prompt: str, on_line: Callable[[str], None] | None = None) -> str:
        """The prompt goes in **after `--`**, and on stdin only when it is huge.

        Two defects, one line apart in history.

        **B92**: `claude --help` declares `--allowedTools <tools...>`, a
        *variadic* option, which swallows every following argument — so a
        vector ending `--allowedTools WebSearch,WebFetch <prompt>` handed the
        brief to the allowlist and the CLI answered

            Error: Input must be provided either through stdin or as a
            prompt argument when using --print

        after the reader had waited out a run. That was fixed by moving the
        prompt to stdin.

        **B125**: stdin is a *pipe*, and on Windows the pipe crosses a
        `claude.cmd` shim into node. When it does not arrive, the CLI says
        "Warning: no stdin data received in 3s, proceeding without it" and then
        fails with B92's own message — on a machine where the same code path
        had worked minutes earlier. The reader pasted exactly that.

        `--` ends option parsing, which solves B92 without a pipe: no argument
        order can consume the prompt, and nothing has to survive a shim. The
        stdin path stays for a prompt longer than `MAX_PROMPT_ARGUMENT`, since
        Windows caps a command line at 32,767 characters.

        `test_the_harness_command_line_is_one_the_cli_accepts` runs the real
        CLI with an empty prompt and asserts its only complaint is the empty
        prompt, which is free and needs no API call. Every previous gate here
        asserted the *shape* of `args` and none asserted the CLI would take
        them — the same mistake as the twelve tray tests that passed on a
        `main.rs` which could not parse (B89).

        **And the output is read as it arrives, since B121.** It used to be
        `subprocess.run(capture_output=True)`, which is a decision to learn
        nothing until the process is over; `on_line` (or `self.on_action`) now
        receives one line per action the agent takes, while it takes it.
        """
        if self.harness.id == "opencode":
            _ensure_opencode_agent()
        command = command_for(self.harness)
        say = on_line if on_line is not None else self.on_action

        if self.harness.prompt_argument and len(prompt) <= MAX_PROMPT_ARGUMENT:
            # `--` first: it ends option parsing, so a variadic option cannot
            # eat the prompt and the prompt cannot be read as an option.
            code, stdout, stderr = self._stream(
                [*command, "--", prompt], subprocess.DEVNULL, say
            )
        else:
            fd, stdin_path = tempfile.mkstemp(prefix="kriko-harness-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stdin_write:
                    stdin_write.write(prompt)
                with open(stdin_path, "r", encoding="utf-8") as stdin_read:
                    code, stdout, stderr = self._stream(command, stdin_read, say)
            finally:
                os.remove(stdin_path)

        if code != 0:
            envelope = _envelope(stdout) if self.harness.structured else {}
            # Metered before raising. A run that failed on its fourth search
            # still spent the reader's subscription on three, and a plane that
            # only counts what succeeded is a plane whose cost column lies.
            self._meter(envelope)
            reason = _why(envelope, stdout, stderr)
            hint = _hint(reason)
            raise RuntimeError(
                f"{self.harness.label} exited {code}: {reason}"
                + (f" -- {hint}" if hint else "")
            )
        if not self.harness.structured:
            return stdout
        return self._unwrap(stdout)

    def _stream(self, command, stdin_read, say) -> tuple[int, str, str]:
        """Run the CLI, reading its output line by line as it is produced.

        Three threads' worth of care for one subprocess, and each one is
        answering a failure this file has already had:

        * **stdout is read in this thread**, so a reader watching the job log
          sees a line the moment the CLI writes it rather than when the pipe's
          buffer happens to flush. It is also why nothing here calls
          `communicate()`.
        * **stderr is drained by its own thread.** A CLI that fills the stderr
          pipe while nobody is reading it blocks forever, and "the harness
          plane hangs on some machines and not others" is the worst possible
          shape for that bug.
        * **The timeout is a timer that kills**, rather than an argument to
          `run`. A `TimeoutExpired` from `run` gives back what was captured; a
          streamed run has already reported everything it saw, so the kill only
          needs to end the process — and the reader has the transcript of what
          it was doing when it stopped, which is the thing the old timeout
          never produced.

        Narration is capped (`MAX_NARRATED`) and never fatal: a log line that
        cannot be written is a worse log, and losing a completed run of real
        research to it would be absurd.
        """
        self.transcript = ""
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed executable, no shell
                command,
                stdin=stdin_read,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, **self.harness.env},
                cwd=os.path.expanduser("~"),
                shell=self._needs_shell(command),
                # POSIX only (Windows accepts and ignores it — see
                # `subprocess._execute_child`'s `unused_start_new_session`).
                # It is what makes `_kill_tree` able to reach a child at all:
                # without its own session, a killed `cmd.exe` (or a shell
                # wrapper) leaves whatever it spawned running past the
                # deadline, still holding the reader's subscription on a
                # search that will never be read.
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise NoHarness(
                f"{self.harness.label} is not on PATH ({self.harness.executable})"
            ) from exc

        said: list[str] = []
        errors: list[str] = []
        drain = threading.Thread(
            target=self._drain, args=(proc.stderr, errors), daemon=True
        )
        drain.start()

        expired = threading.Event()

        def _give_up() -> None:
            expired.set()
            self._kill_tree(proc)

        timer = threading.Timer(self.timeout, _give_up)
        timer.start()
        narrated = 0
        try:
            for line in proc.stdout:
                self._keep(line)
                # Checked before narration, every line: a run an agent has
                # gone quiet on (nothing left to say for `MAX_NARRATED` lines,
                # or a CLI that streams no text) must still be interruptible.
                # Left to propagate on purpose — the `finally` below kills the
                # tree, and whatever `check_cancelled` raised (a `Cancelled`,
                # in production) reaches the caller exactly as raised, so a
                # cancelled run reads as cancelled rather than as a crash.
                if self.check_cancelled is not None:
                    self.check_cancelled()
                if say is None:
                    continue
                if narrated >= MAX_NARRATED:
                    # Said once, then silence. A cap that stops quietly leaves
                    # the reader looking at exactly what B121 fixed — a run
                    # that went silent — with no way to tell the two apart.
                    if narrated == MAX_NARRATED:
                        narrated += 1
                        try:
                            say(
                                f"(still running; the next actions are not "
                                f"shown — {MAX_NARRATED}-line cap)"
                            )
                        except Exception:  # noqa: BLE001
                            say = None
                    continue
                spoken = self._narrate(line)
                if not spoken:
                    continue
                narrated += 1
                said.append(spoken)
                try:
                    say(spoken)
                except Exception:  # noqa: BLE001 — see the docstring
                    say = None
            proc.wait()
        finally:
            timer.cancel()
            # A cancellation (or any other exception) escaping the loop above
            # leaves before `proc.wait()`, and the child — the whole tree, for
            # a `.cmd` shim whose real work is one level below `cmd.exe` — must
            # not be left running past whatever stopped this thread reading
            # it. Idempotent: a process the timeout path already killed, or
            # one that finished on its own, answers `poll()` with a code and
            # this does nothing. It happens *before* the drain thread is
            # joined and before the pipes are closed, because both of those
            # wait on a reader that only returns when the child's pipe reaches
            # end of file: closing a buffered pipe takes the same lock the
            # blocked `readline` holds, so a teardown in the other order waits
            # out the very process it is trying to abandon.
            if proc.poll() is None:
                self._kill_tree(proc)
            drain.join(timeout=5.0)
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except Exception:  # noqa: BLE001
                    pass

        self.actions = said
        if expired.is_set():
            raise TimeoutError(
                f"{self.harness.label} did not finish within {int(self.timeout)}s"
            )
        return proc.returncode or 0, self.transcript, "".join(errors)

    @staticmethod
    def _kill_tree(proc) -> None:
        """End the whole process, not just the one pid this object holds.

        `_needs_shell` means the pid here is sometimes `cmd.exe`, whose real
        child (the CLI, and whatever it forked for a fetch) `proc.kill()`
        never touches — a run declared timed out would keep spending the
        reader's subscription in the background, invisibly, past the
        deadline this exists to enforce. `start_new_session=True` on spawn is
        what makes a tree kill possible on POSIX (`killpg` reaches the whole
        session); on Windows `taskkill /T` is the documented way to end one.
        Every step is best-effort — a process that is already gone by the
        time this runs is the good outcome, not a failure to report.
        """
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001 — already gone is the good case
            pass
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _needs_shell(command: list[str]) -> bool:
        """Whether this vector can only start through `cmd.exe`.

        Windows `CreateProcess` (what `subprocess.Popen(shell=False)` calls)
        needs a PE image; it cannot launch a `.cmd`/`.bat` file directly and
        fails before a byte of stdin is written — `WinError 193: %1 is not a
        valid Win32 application`, or `WinError 2`, depending on the build.
        `claude.cmd` next to no `claude.exe` at all is exactly what npm's own
        global installer for Claude Code produces, and it is exactly what
        `locate()`'s suffix search (`_SUFFIXES`) is written to find. `shell=True`
        on Windows already does the right thing with a list of arguments —
        Python quotes each one with `list2cmdline` before handing the joined
        string to `%ComSpec% /c` — so this is the one platform difference the
        caller needs, never a rewrite of the command itself.
        """
        return (
            os.name == "nt"
            and bool(command)
            and command[0].lower().endswith((".cmd", ".bat"))
        )

    @staticmethod
    def _drain(pipe, into: list) -> None:
        try:
            for line in pipe:
                into.append(line)
                if len(into) > 400:
                    del into[: len(into) - 400]
        except Exception:  # noqa: BLE001 — a closed pipe is how this ends
            pass

    def _keep(self, line: str) -> None:
        """Append to the bounded transcript the reply is parsed out of."""
        self.transcript += line
        if len(self.transcript) > TRANSCRIPT_TAIL:
            self.transcript = self.transcript[-TRANSCRIPT_TAIL:]

    def _narrate(self, line: str) -> str:
        """One output line, as something worth logging — or nothing.

        A CLI that answers in prose (`structured=False`) has no events to
        translate, so its own words are the narration. One that answers in
        JSON is translated by `narrate`, and a line that is neither is
        machinery: partial frames, blank lines, a banner.
        """
        if not self.harness.structured:
            return _short(line, 200)
        try:
            event = json.loads(line)
        except ValueError:
            return ""
        return narrate(event) if isinstance(event, dict) else ""

    def _meter(self, envelope: dict) -> None:
        """Stamp what the reply admits to spending. Read duck-typed by
        `tasks.py`, and left as `None` when the CLI said nothing — the
        difference between "spent nothing" and "cannot count"."""
        tokens = _tokens(envelope.get("usage") or {})
        if tokens:
            self.tokens_used = tokens
        cost = envelope.get("total_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            self.cost_usd = float(cost)

    def _unwrap(self, stdout: str) -> str:
        """The assistant's text out of the CLI's JSON envelope, plus the usage.

        The shape-reading is `_envelope`'s, which the failure path shares:
        one object, an array of stream messages, or one object per line. A
        reply that is not JSON at all is handed back as prose rather than
        discarded — the findings fence may still be in it.
        """
        envelope = _envelope(stdout)
        if not envelope:
            return stdout

        self._meter(envelope)
        if envelope.get("is_error"):
            # Same treatment as a non-zero exit, because it is the same
            # failure: `claude -p` reports a refusal, a limit or a billing
            # stop in the envelope and exits 0 about it.
            reason = _why(envelope, stdout, "")[:500]
            hint = _hint(reason)
            raise RuntimeError(
                f"{self.harness.label} reported an error: {reason}"
                + (f" -- {hint}" if hint else "")
            )
        result = envelope.get("result")
        return result if isinstance(result, str) else stdout


def _site(url: str) -> str:
    """The host, for the log line. Not a parse — just the readable part."""
    without = url.split("://", 1)[-1]
    return without.split("/", 1)[0]
