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

* **The spawned agent gets no Kriko MCP tools, and no write tools.** It could
  have been handed Kriko's own `submit_findings` — but then claims would arrive by
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

  **The one server it is given is a page reader (B155).** Sites behind
  Cloudflare's AI-bot blocking answer the CLI's own fetcher with a 403, and
  Kriko never changes what a CLI fetches with. So a CLI whose row declares a
  `reader` and whose `--help` declares its config flag is handed a per-run
  config, written into the run's own folder, naming one keyless hosted server
  whose only tool reads a page. It reads and writes nothing, so it stays inside
  the "search and fetch" grant below; `--strict-mcp-config` still keeps every
  other server out.
* **`--allowedTools` is an explicit allowlist, never a denylist.** Handing a
  coding agent `Bash` to research a car is a remote-code path with extra
  steps. `SEARCH_TOOLS` is the whole grant, and it is search and fetch (plus,
  where attached, the page reader's fetch).
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
from app.loginpath import child_env, login_path
from app.winprocess import hidden_startup
import sys
import tempfile
import tomllib
import time
from contextlib import contextmanager
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from kriko.research.agent import REFUSED_PAGE, AgentResearcher
from kriko.research.base import Document, Finding, ResearchTask

#: Everything the spawned agent is allowed to do. Read the module docstring
#: before adding to this: a research plane that can write files or run shell
#: commands is not a research plane.
SEARCH_TOOLS = ("WebSearch", "WebFetch")

#: The page reader (B155): a keyless hosted MCP server whose one tool reads a
#: page for the agent. Exa's, because it is free, needs no key of the reader's,
#: and read all four pages a Claude Code quick look had been refused in a probe
#: (2026-09-29; the CLI's own fetcher got a 403 from each). Only its fetch tool
#: is granted: search was never refused, and a second search tool is only a
#: second place to spend the run's budget. The tool names are read off the
#: server's own `tools/list`, not written from memory.
READER_SERVER = "exa"
READER_URL = "https://mcp.exa.ai/mcp"
READER_TOOLS = ("web_fetch_exa",)

#: Where the per-run config is written, inside the run's own folder.
READER_CONFIG_FILE = "kriko-page-reader.mcp.json"

#: How much of a page one read returns. The server's default is 3,000
#: characters, which is a lead paragraph; a quote has to come from the part of
#: the page that names the fault. Measured against the server: it returns as
#: much as it is asked for, so this is a ceiling the agent is told to pass.
READER_PAGE_CHARS = 12000

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

#: How long a *question to a CLI about itself* may take — `--help`, `models`.
#: Short on purpose: the Agents screen asks all of these on load, so the worst
#: case a reader waits is this times the number of CLIs installed, and a probe
#: that is slow is already telling us its answer will not be worth waiting for.
#: A probe that times out reads as "declares nothing extra", which costs the
#: reader the hygiene flags and never the plane.
HELP_TIMEOUT_SECONDS = 12.0

#: Said to every CLI child, because we write to it in UTF-8 and read it back
#: as UTF-8. A Python CLI on Windows otherwise decodes a piped stdin with the
#: ANSI code page and `surrogateescape`: the brief's `”` (E2 80 9D) arrives as
#: `â€\udc9d`, 0x9D being the one byte cp1252 leaves undefined. Mistral Vibe
#: took that text and then died writing it to its own session log
#: ("surrogates not allowed") — every case of the reader's bench on
#: 2026-09-26. Harmless to a CLI that is not Python.
CHILD_ENCODING_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _minutes(seconds: float) -> str:
    """`75` → `1m 15s`; `40` → `40s`. For a log line a person reads."""
    whole = int(seconds)
    return f"{whole // 60}m {whole % 60:02d}s" if whole >= 60 else f"{whole}s"


def _lines(stream, tick: float):
    """`stream`'s lines, with a `None` every `tick` seconds it stays silent.

    A blocking read on a pipe cannot be interrupted, and `for line in stream`
    is exactly that — which made the cancel check that follows it worth nothing
    during the only period a run is worth cancelling. So the read happens on
    its own thread and the caller waits on a queue with a timeout, which it
    *can* come back from.

    The thread is a daemon and is never joined: the process it is reading from
    is killed by the caller's `finally`, which closes the pipe and ends the
    read. Waiting for it would reintroduce the block this removes.
    """
    import queue as _queue

    box: _queue.Queue = _queue.Queue(maxsize=256)
    done = object()

    def _read() -> None:
        try:
            for line in stream:
                box.put(line)
        except (ValueError, OSError):
            # The pipe was closed under us, which is what a kill looks like
            # from this side. Not an error — it is the designed way out.
            pass
        finally:
            box.put(done)

    threading.Thread(target=_read, daemon=True).start()
    while True:
        try:
            item = box.get(timeout=tick)
        except _queue.Empty:
            yield None
            continue
        if item is done:
            return
        yield item


class NoHarness(RuntimeError):
    """The harness plane was asked for and no harness CLI is on this machine."""


@dataclass(frozen=True)
class PageReader:
    """How one CLI is handed the page reader (B155): three facts about the CLI.

    A row that carries one says "this CLI takes a per-run MCP config, and this
    is how its allowlist spells an MCP tool". Whether *this machine's* build
    does is still asked of its `--help` (`reader_declared`), the rule every
    other flag here follows: an older build keeps the plane and loses the
    reader.
    """

    #: The flag that takes a config file for this run's MCP servers.
    config_flag: str
    #: The allowlist flag in the row's `args`, which the reader's tools join.
    grant_flag: str
    #: How the allowlist names an MCP server's tool, with `{server}` and
    #: `{tool}`. Read off the CLI's own documentation, per row.
    tool: str


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
    protocol: str = "claude"
    model_flag: str = ""
    required: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    #: One paragraph appended to `CONTRACT`, for a CLI whose tool set differs
    #: from what the shared contract assumes. The contract says "only the web
    #: search and web fetch tools" because every CLI here had both — and the
    #: first one that has only `web_fetch` would otherwise be sent looking for
    #: a tool it does not own. Per-harness prose, never per-category: nothing
    #: here may name a product, a make or a subject.
    contract_note: str = ""
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
    #: Flags with a value, added on the same rule as `preferred`: only when
    #: this machine's `--help` declares the flag.
    preferred_values: tuple[tuple[str, str], ...] = ()
    #: How this CLI is handed the page reader, or `None` for a CLI that is not
    #: (yet) verified to take one. See `PageReader`.
    reader: PageReader | None = None
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
    #: A flag that takes the prompt as its value (`-p` for `agy`), for a CLI
    #: with no `--` separator convention. Takes precedence over both prompt
    #: paths above; stdin is never used for it, because a prompt on stdin is
    #: silently ignored there rather than read — a run that researches nothing
    #: on the reader's quota is the failure this rules out.
    prompt_flag: str = ""
    #: How this CLI is told that more messages will arrive on stdin while it
    #: is running — the difference between a note nobody reads and a reply the
    #: agent acts on.
    #:
    #: **This is what B120 left open, and it is not free.** Every other prompt
    #: path here was moved *off* stdin (see `prompt_argument`): a pipe that
    #: crosses a `claude.cmd` shim into node is the B125 scar, and it failed
    #: silently. Streaming input puts the prompt back on that pipe, because a
    #: CLI reading messages has no other place to read the first one from. The
    #: trade is accepted only where it buys something — a run the reader can
    #: actually answer — and only when the CLI *declares* the flag, with the
    #: ordinary one-shot vector still there for every other run. The silent
    #: half of the scar is closed by `CONVERSATION_START_SECONDS`: a child
    #: that never speaks is abandoned in a minute rather than in the timeout,
    #: and the run is retried the old way.
    reply_flag: str = ""
    reply_value: str = ""
    #: An environment variable that names the model, for a CLI with no
    #: per-run `--model` flag. `vibe` is the case: its model is a *config*
    #: field (`active_model`) and its config layer reads `VIBE_*` out of the
    #: environment — so the choice is per-run after all, just not as an
    #: argument. Consulted only when `model_flag` is empty, because a flag is
    #: the CLI's own answer and an env var is read off its config schema.
    model_env: str = ""
    #: The flag that caps what one run may spend, and the flag that caps how
    #: many assistant turns it may take. Empty means this CLI offers no such
    #: ceiling, and the only ones are Kriko's own — the prompt's source
    #: budget, and `TIMEOUT_SECONDS`.
    #:
    #: **This is the scale dial reaching the CLI.** Before it, a Quick run and
    #: a Deep run differed only in how many of the agent's findings were
    #: *kept*: the agent had already read thirty pages either way, on the
    #: reader's subscription. A ceiling the CLI itself enforces is the only
    #: one that saves anything, which is the whole of "I don't want my agent
    #: to search 30 sources, maybe I want 3".
    budget_flag: str = ""
    turns_flag: str = ""
    #: How many assistant turns one source is worth, for `turns_flag`. A run
    #: allowed seven sources needs turns for the searches, the reads and the
    #: report, so this is deliberately generous: the flag is a runaway stop,
    #: not a budget, and a run killed one turn short of its report has spent
    #: everything and returned nothing.
    turns_per_source: int = 4
    #: True when this CLI must run under a `HOME` Kriko builds rather than the
    #: reader's own. See `_workspace` — it is how a permission policy is
    #: granted for the length of one run without ever rewriting a file the
    #: reader owns.
    sandbox_home: bool = False
    #: The flag is documented but not in the top-level `--help`, so the
    #: declared-flag check in `command_for` cannot see it. `opencode --help`
    #: describes the TUI; `--model` belongs to `opencode run`. Set only with
    #: the docs to point at.
    model_unlisted: bool = False
    #: Where this CLI's model names come from — never from Kriko. `"help"`
    #: reads the names the `--model` line of `--help` quotes (Claude Code has
    #: no `models` command, and its help is revised with every model it
    #: ships); `"models"` runs `<cli> models` and reads its list. Empty means
    #: the CLI offers no list and the field is free text. Either way the reader
    #: can type past the list — the CLI judges the name, not Kriko.
    model_source: str = ""
    #: One line saying what a valid name looks like, for the dropdown's hint.
    model_hint: str = ""
    #: How hard the CLI should think, per run. A second dial beside the model
    #: and a cheaper one to turn: dropping a survey run from `high` to `low`
    #: costs a fraction of what switching the model does and changes nothing
    #: about which account pays. Passed only when `--help` declares the flag —
    #: the same rule `preferred` follows, because a reader on an older build
    #: must lose the dial rather than the plane.
    effort_flag: str = ""
    #: The levels this CLI documents. Read out of its own `--help`, never
    #: invented: `claude` lists five and `agy` three, and a level neither of
    #: them accepts is a run that dies on argument parsing.
    effort_choices: tuple[str, ...] = ()
    effort_hint: str = ""
    #: Where to get it, in the reader's words. Shown when the CLI is missing,
    #: so a dead link here is worse than none — only official install pages.
    download_url: str = ""
    #: The one command that installs it, for the missing-harness card.
    install_hint: str = ""
    #: The same install as a PowerShell script the app can run for the reader
    #: (`app/agentinstall.py`), taken from the vendor's own Windows
    #: instructions. Empty means no one-click install: the card shows the
    #: hint and the download page instead.
    install_command: str = ""
    #: What account it bills to. Every headless plane spends *something* —
    #: a subscription, a quota, a key — and "no marginal cost" is only true
    #: once the reader knows which one they already pay.
    needs_account: str = ""
    #: Where this CLI installs itself, relative to the reader's home, for when
    #: `PATH` does not carry it. See `locate`.
    homes: tuple[str, ...] = (
        ".local/bin",
        "AppData/Local/Programs",
        "AppData/Local/agy/bin",
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
KNOWN: tuple[Harness, ...] = (
    Harness(
        "claude-code",
        "Claude Code",
        "claude",
        _claude_args(),
        download_url="https://code.claude.com/docs",
        install_hint="winget install Anthropic.ClaudeCode",
        install_command="irm https://claude.ai/install.ps1 | iex",
        needs_account="a Claude subscription or API billing; log in once with an interactive `claude` session first",
        model_flag="--model",
        model_source="help",
        model_hint="an alias or a full name, as `claude --help` names them — the CLI judges it, not Kriko",
        effort_flag="--effort",
        effort_choices=("low", "medium", "high", "xhigh", "max"),
        effort_hint="how hard to think — `claude --help` lists these five",
        # `--max-budget-usd <amount>`, and its help says "only works with
        # --print", which is the only mode this plane runs in. The scale dial
        # reached one CLI before this line; the reader's whole point was not
        # spending tokens they did not choose to spend, and the harness they
        # are trying *not* to spend on was the one with no ceiling.
        budget_flag="--max-budget-usd",
        # `--input-format stream-json`, whose help says "only works with
        # --print" — which is the mode this plane already runs in, so the
        # conversational vector is the streaming one plus this flag and
        # nothing else. Probed as a *flag* rather than by looking for
        # "stream-json" in the help text, because that word is also in
        # `--output-format`'s line and would have said yes on a CLI that only
        # streams outward.
        reply_flag="--input-format",
        reply_value="stream-json",
        # `--strict-mcp-config` with no `--mcp-config` is zero MCP servers;
        # `--safe-mode` drops the rest of the reader's configuration — their
        # `CLAUDE.md`, hooks, skills, plugins, output style — while leaving
        # auth, the built-in tools and permissions alone. Both are what this
        # spawn already claimed to be.
        preferred=("--strict-mcp-config", "--safe-mode"),
        # `--allowedTools` only *permits* the two search tools; every other
        # built-in tool's definition is still loaded into the context of
        # every turn. `--tools` is the list of tools that exist at all.
        # Measured on 2.1.289, one `-p` turn: 29 327 input tokens of fixed
        # context without it, 5 719 with it. MCP tools (the page reader
        # below) are not in the built-in set and are not affected.
        preferred_values=(("--tools", ",".join(SEARCH_TOOLS)),),
        # **The page reader (B155).** Sites behind Cloudflare's bot blocking
        # answer this CLI's own fetcher (`Claude-User`) with a 403, on 2.1.283
        # and 2.1.284 alike. `--mcp-config <configs...>` "loads MCP servers
        # from JSON files", and with `--strict-mcp-config` those are the only
        # servers the run has; an MCP tool is allowed by the name
        # `mcp__<server>__<tool>` (Claude Code's permission-rule syntax). Its
        # own docs say a `-p` run waits up to `MCP_TIMEOUT` for the server to
        # connect before the first turn, so the tool is there when the agent
        # starts. `--safe-mode`'s help lists "MCP servers" among the
        # customizations it drops without saying whether an explicit
        # `--mcp-config` survives it; the run's `system/init` line is logged
        # ("started ...; exa connected") so a reader can see which it was.
        reader=PageReader("--mcp-config", "--allowedTools", "mcp__{server}__{tool}"),
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
        download_url="https://opencode.ai/download",
        needs_account="a model account or API key of your own (or a free/local model)",
        structured=False,
        model_flag="--model",
        model_unlisted=True,
        model_source="models",
        model_hint="provider/name, as `opencode models` lists them",
        # The bash installer is the right line on macOS and Linux and is not
        # runnable on the reader's machine, which is Windows. A hint nobody
        # can paste is a hint that teaches the reader the screen is decorative.
        install_hint=(
            "npm install -g opencode-ai"
            if os.name == "nt"
            else "curl -fsSL https://opencode.ai/install | bash"
        ),
        # Its own installer puts the binary in `~/.opencode/bin`, and Windows
        # installs land under `%LOCALAPPDATA%\Programs\opencode`. Neither is
        # on the `PATH` a desktop shell inherits at login — which is the whole
        # reason `locate` looks past `PATH` at all.
        # Its own installer puts the binary in `~/.opencode/bin`, and npm's
        # global install puts a shim in `%APPDATA%\npm`. Neither is on the
        # `PATH` a desktop shell inherits at login, which is the whole reason
        # `locate` looks past `PATH`.
        #
        # **`AppData/Local/Programs` is deliberately not here, and the default
        # list is why this row needs its own.** Windows paths are
        # case-insensitive, so that directory matched
        # `…/Programs/OpenCode/OpenCode.exe` — an unrelated Electron
        # application with the same name — and Kriko then ran a GUI app with
        # `--help` and waited for it. A fallback guess that is wrong must cost
        # nothing, and a guess that matches the wrong binary costs everything.
        homes=(
            ".opencode/bin",
            ".local/bin",
            "AppData/Roaming/npm",
            ".npm-global/bin",
            "node_modules/.bin",
            "bin",
        ),
    ),
    Harness(
        "antigravity-cli",
        "Antigravity CLI",
        "agy",
        ("--output-format", "stream-json"),
        download_url="https://antigravity.google/download",
        install_hint=(
            "irm https://antigravity.google/cli/install.ps1 | iex"
            if os.name == "nt"
            else "curl -fsSL https://antigravity.google/cli/install.sh | bash"
        ),
        install_command="irm https://antigravity.google/cli/install.ps1 | iex",
        needs_account="a Google account (free-tier quotas) or a Gemini API key; sign in once with an interactive `agy` session first",
        protocol="agy",
        prompt_argument=False,
        prompt_flag="-p",
        required=("--output-format",),
        preferred=("--disable-slash-commands",),
        model_flag="--model",
        model_source="models",
        model_hint="an id from `agy models`",
        effort_flag="--effort",
        effort_choices=("low", "medium", "high"),
        effort_hint="reasoning effort — `agy --help` names these three",
        capabilities=("headless", "streaming", "web-search", "web-fetch",
                      "model-selection"),
        # **This is the reader's "I can only use Claude Code, not
        # Antigravity".** Verified against the real CLI: `agy` runs headless
        # with `permission_mode: request-review`, under which `search_web`
        # needs no approval and `read_url_content` does. Nobody can answer a
        # prompt in print mode, so every run searched six times, tried to read
        # its first page, was auto-denied, and returned an empty reply after
        # spending 80k tokens of the reader's quota. Exit code 0 throughout.
        #
        # The grant is one line in the CLI's own settings file — and Kriko
        # writes it into a `HOME` that lasts for the run rather than into the
        # reader's, for the reason the whole `_workspace` exists: a research
        # plane may not leave a permission behind it. Verified that the login
        # survives, because `agy` keeps its token in the OS keyring rather
        # than under `HOME`.
        sandbox_home=True,
        turns_flag="",
        budget_flag="",
    ),
    # Verified against Mistral Vibe 2.25.5. Every argument below is one the
    # CLI's own `--help` declares, and every value was read off the installed
    # package rather than guessed:
    #
    # * `--agent auto-approve` is a **builtin** (`vibe.core.agents.models`
    #   `BUILTIN_AGENTS`), so there is no profile file to write and nothing
    #   to keep in step with a schema Kriko does not own. The earlier vector
    #   named `kriko-research`, a custom agent — which is why this row could
    #   never be verified: the file it needed had a shape nobody had read.
    # * `--enabled-tools` "in programmatic mode (-p) … disables all other
    #   tools", so naming the two web tools *is* the sandbox. The names are
    #   the snake_case of the tool classes (`WebSearch`, `WebFetch` in
    #   `vibe/core/tools/builtins/`), which is how `BaseTool` derives them.
    # * `--trust` is the CLI's own documented answer to "use this for
    #   non-interactive automation": without it the run stops on a trust
    #   prompt that headless mode cannot answer — `agy`'s failure again.
    # * `--output streaming` prints one JSON history entry per message, which
    #   is what `narrate` turns into the job log and `_unwrap` reads the reply
    #   out of. It carries no usage, so this plane's cost columns stay NULL
    #   rather than being filled with a guess.
    Harness(
        "mistral-vibe", "Mistral", "vibe",
        ("--output", "streaming", "--agent", "auto-approve", "--trust",
         "--enabled-tools", "web_search", "--enabled-tools", "web_fetch"),
        download_url="https://docs.mistral.ai/vibe/code/cli/install-setup",
        install_hint=(
            "pip install mistral-vibe"
            if os.name == "nt"
            else "curl -LsSf https://mistral.ai/vibe/install.sh | bash"
        ),
        # Mistral's own installer installs `uv` when it is missing and then
        # `uv tool install mistral-vibe`; this is that, with uv's Windows installer.
        install_command=(
            "if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {"
            " irm https://astral.sh/uv/install.ps1 | iex;"
            " $env:Path = \"$HOME\\.local\\bin;$env:Path\" };"
            " uv tool install mistral-vibe"),
        needs_account="a Mistral account or API key (MISTRAL_API_KEY); run `vibe --setup` once first",
        protocol="vibe", prompt_argument=False,
        required=("--output", "--agent", "--enabled-tools", "--prompt"),
        capabilities=("headless", "streaming", "web-search", "web-fetch",
                      "model-selection", "budget", "turn-cap"),
        # No `--model` flag exists. The model is a config field, and the
        # config's environment layer reads `VIBE_*` with a nested delimiter —
        # so `VIBE_ACTIVE_MODEL` is the per-run switch, read off
        # `vibe/core/config/layers/environment.py` rather than invented.
        model_env="VIBE_ACTIVE_MODEL",
        model_source="vibe-config",
        effort_flag="vibe-thinking",
        # This CLI's Mistral backend maps low to `none` (rejected by GLM)
        # and medium/high/max to `high`; only expose the effective level.
        effort_choices=("high",),
        # No list either: `vibe` has no `models` command and its `--help`
        # names none, so the field is free text rather than a list typed here.
        model_hint="a Mistral model alias — the CLI judges it, not Kriko",
        # The only CLI here that will stop itself on money. Both are
        # documented as applying "only … in programmatic mode with -p",
        # which is the mode this plane runs in and no other.
        budget_flag="--max-price",
        turns_flag="--max-turns",
        sandbox_home=True,
    ),
    # Verified against GitHub Copilot CLI 1.0.48 on the reader's own machine,
    # which is where this row came from: `copilot` was on PATH, answered
    # `--help`, ran a prompt and returned a reply — and Kriko had no row for
    # it, so the Agents screen said three agents where there were four. That
    # is the whole of the reader's "detected harnesses aren't including all".
    #
    # Every value below was read off the installed CLI rather than a doc page:
    #
    # * `--output-format json` is **JSONL, one object per line** (its own help
    #   says so), ending in a `{"type": "result", "exitCode": n}` line. The
    #   reply is in the `assistant.message` events, which is why this needs
    #   its own protocol rather than reusing `claude`'s `result.result`.
    # * `--allow-all-tools` is what its help gives as the non-interactive
    #   example, and without it a headless run stops on a permission prompt
    #   nobody can answer — `agy`'s failure, one CLI further on. `--no-ask-user`
    #   closes the other door, the `ask_user` tool.
    # * `--available-tools web_fetch` is the sandbox: its help reads "only
    #   these tools will be available to the model", so naming one name is
    #   the grant. Asked to name its own tools, this CLI listed `powershell`,
    #   `write_powershell`, `create`, `edit`, `sql` and a dozen more — every
    #   one of which a research run must not have.
    # * **It has no web *search* tool.** `web_fetch` is the only reading tool
    #   it owns, which is why `capabilities` does not claim search and why
    #   this is the one row that carries a `contract_note`.
    # * `--disable-builtin-mcps` drops its GitHub MCP server, and
    #   `--no-custom-instructions` the reader's own instruction files: the
    #   same hygiene `--safe-mode` buys on Claude Code.
    # * **No `reader` (B155), on purpose.** It declares `--additional-mcp-config`
    #   ("JSON string or file path (prefix with @)"), but `--available-tools`
    #   is a whole tool set and nothing in its help says how a tool from an MCP
    #   server is named inside it. Guessing would either leave the reader
    #   outside the set or widen it; a row gets a `reader` once a run has shown
    #   the spelling, and `test_the_page_reader.py` pins which rows have one.
    Harness(
        "github-copilot", "GitHub Copilot CLI", "copilot",
        ("--output-format", "json", "--allow-all-tools", "--no-ask-user",
         "--available-tools", "web_fetch",
         "--disable-builtin-mcps", "--no-custom-instructions",
         "--no-auto-update", "--no-color", "--log-level", "none"),
        download_url="https://docs.github.com/copilot/how-tos/copilot-cli",
        install_hint=(
            "winget install GitHub.Copilot"
            if os.name == "nt"
            else "npm install -g @github/copilot"
        ),
        needs_account="a GitHub Copilot subscription; run `copilot login` once first",
        protocol="copilot", prompt_argument=False, prompt_flag="-p",
        required=("--output-format", "--allow-all-tools", "--available-tools"),
        model_flag="--model", model_unlisted=True, model_source="help",
        model_hint=(
            "a model id your Copilot plan includes — it refuses an unavailable "
            "one by name before spending anything"
        ),
        effort_flag="--effort",
        effort_choices=("low", "medium", "high", "xhigh"),
        effort_hint="reasoning effort — `copilot --help` names these four",
        capabilities=("headless", "streaming", "web-fetch", "model-selection"),
        contract_note=(
            "\n**This agent has no web search tool — only `web_fetch`.** Where "
            "the brief says to search, fetch a search engine's own results page "
            "instead (a plain HTML endpoint, not a JavaScript one), read the "
            "links off it, and fetch the pages worth reading. Everything else "
            "about the contract above is unchanged: report what you actually "
            "read, quote it verbatim, and invent nothing.\n"
        ),
        # winget puts the shim under `Links`, the payload under `Packages`,
        # and npm's global install somewhere else again. None of the three is
        # reliably on the `PATH` a desktop shell inherits at login.
        homes=(
            "AppData/Local/Microsoft/WinGet/Links",
            "AppData/Local/copilot/bin",
            "AppData/Roaming/npm",
            ".npm-global/bin",
            "node_modules/.bin",
            ".local/bin",
            "bin",
        ),
    ),
    Harness(
        "gemini-cli", "Gemini CLI", "gemini",
        ("--output-format", "stream-json", "--approval-mode", "default",
         "--allowed-tools", "google_web_search,web_fetch"),
        download_url="https://geminicli.com/docs/get-started/installation",
        install_hint="npm install -g @google/gemini-cli",
        needs_account="a Google account (free-tier quotas) or a Gemini API key; sign in once with an interactive `gemini` session first",
        protocol="gemini", model_flag="--model", prompt_argument=False,
        sandbox_home=True,
        required=("--output-format", "--approval-mode", "--allowed-tools", "--prompt"),
        capabilities=("headless", "streaming", "web-search", "web-fetch", "model-selection"),
        unusable=("not yet verified against the real CLI — `--allowed-tools` "
                  "is deprecated upstream and the sandbox file it would run "
                  "under is untested, so Kriko will not drive it until they are"),
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

#: Other places a CLI lands that a login `PATH` may still not list (a version
#: manager's shim folder, a package manager's link folder). A fallback only,
#: after `PATH` and the registry's, so a wrong entry costs one missed probe.
_EXTRA_HOMES = (
    ".volta/bin",
    ".bun/bin",
    ".cargo/bin",
    "AppData/Local/pnpm",
    "AppData/Local/Microsoft/WinGet/Links",
    "AppData/Local/Microsoft/WindowsApps",
    "scoop/shims",
)

#: Executable suffixes to try on Windows, where `claude` is `claude.exe` and an
#: npm-installed one is `claude.cmd`. Empty string first: a bare name is right
#: everywhere else, and on Windows `shutil.which` has already handled PATHEXT.
_SUFFIXES = (("", ".exe", ".cmd", ".bat") if os.name == "nt" else ("",))


#: The last line of an npm `cmd-shim` wrapper: the program it hands `%*` to,
#: optionally after `"%_prog%"` (node) for a script target.
_SHIM_TARGET = re.compile(
    r'(?P<node>"%_prog%"\s+)?"%(?:dp0|~dp0)%\\?(?P<target>[^"]+)"\s+%\*', re.IGNORECASE
)


def unshim(command: list[str]) -> list[str]:
    """The same command with npm's `.cmd` wrapper taken out of the way (B151).

    A `.cmd` can only start through `cmd.exe`, and `cmd.exe` ends a command at
    the first newline — so a multi-line brief passed as an argument arrived as
    its first line. The reader's opencode received "# Quick look: what is
    known to go wrong with this one?" and nothing else, every run, and sat
    silent. npm's shims are one line that forwards `%*` to a real program; run
    that program instead and every byte of the argument survives. Anything
    that is not a recognisable shim is returned untouched and still goes
    through `cmd.exe`, exactly as before.
    """
    if os.name != "nt" or not command or not command[0].lower().endswith((".cmd", ".bat")):
        return command
    shim = Path(command[0])
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return command
    found = _SHIM_TARGET.search(text)
    if not found:
        return command
    target = shim.parent / found.group("target").replace("\\", os.sep)
    if not target.is_file():
        return command
    if not found.group("node"):
        return [str(target), *command[1:]] if target.suffix.lower() == ".exe" else command
    node = shim.parent / "node.exe"
    runtime = str(node) if node.is_file() else shutil.which("node")
    return [runtime, str(target), *command[1:]] if runtime else command


#: B152.7: `locate` walks PATH x PATHEXT per CLI — ~7,800 filesystem probes
#: for the roster on this machine, 200 ms a call — and Settings, the agent
#: picker and every research start ask it. Kept for a few seconds, keyed on
#: everything that changes the answer; `forget_located()` is the refresh.
_LOCATED: dict[tuple, tuple[float, str]] = {}
LOCATE_TTL_S = 20.0


def forget_located() -> None:
    _LOCATED.clear()


def locate(one: Harness) -> str:
    """`_locate`, remembered for `LOCATE_TTL_S` (see `_LOCATED`)."""
    # `expanduser` rather than `Path.home()`: the key only has to *name* the
    # home directory, and `Path()` picks its flavour from `os.name` at call
    # time — so a test that flips `os.name` to probe Windows behaviour makes
    # `Path.home()` build a `WindowsPath`, which cannot be instantiated on a
    # POSIX runner at all (NotImplementedError, before `_locate` runs).
    # `expanduser` reads the same env vars and works on both.
    key = (one.executable, one.homes, login_path(),
           os.environ.get(DIRS_ENV, ""), os.path.expanduser("~"))
    now = time.monotonic()
    hit = _LOCATED.get(key)
    if hit and now - hit[0] < LOCATE_TTL_S:
        return hit[1]
    found = _locate(one)
    _LOCATED[key] = (now, found)
    return found


def _locate(one: Harness) -> str:
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
    # The process's PATH first, then what a fresh login would add: a CLI the
    # reader installed after this app started is on the registry's PATH only.
    found = shutil.which(one.executable) or shutil.which(one.executable, path=login_path())
    if found:
        # PATHEXT is conventionally spelled in upper case
        # (".COM;.EXE;.BAT;.CMD") and `shutil.which` returns whatever case
        # it matched in, so an npm-installed CLI resolves to "...\claude.CMD"
        # next to every other path's lower-case suffix. Windows paths are
        # case-insensitive either way, so this only matters where the path
        # is shown to the reader (Settings → Your agents, settings-23).
        if os.name == "nt":
            stem, dot, suffix = found.rpartition(".")
            if dot and suffix.lower() in ("com", "exe", "bat", "cmd"):
                found = f"{stem}.{suffix.lower()}"
        return found
    home = Path.home()
    if one.id == "codex" and os.name == "nt":
        packaged = home / "AppData" / "Local" / "OpenAI" / "Codex" / "bin"
        candidates = sorted(packaged.glob("*/codex.exe"))
        if candidates:
            return str(max(candidates, key=lambda p: p.stat().st_mtime))
    roots = [Path(d) for d in os.environ.get(DIRS_ENV, "").split(os.pathsep) if d]
    roots += [home / part for part in (*one.homes, *_EXTRA_HOMES)]
    roots += sorted(home.glob("AppData/Roaming/Python/Python*/Scripts"), reverse=True)
    for root in roots:
        for suffix in _SUFFIXES:
            candidate = root / f"{one.executable}{suffix}"
            try:
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)
            except OSError:
                continue
    return ""


# The desktop roster requested by the reader. Each invocation starts a new chat.
KNOWN = tuple(h for h in KNOWN if h.id in {"claude-code", "antigravity-cli", "mistral-vibe"}) + (
    Harness("codex", "Codex", "codex", ("exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only"),
            protocol="codex", model_flag="--model", model_unlisted=True,
            effort_flag="codex-thinking", effort_choices=("low", "medium", "high", "xhigh"),
            model_source="codex-cache", download_url="https://developers.openai.com/codex/cli",
            install_hint="npm install -g @openai/codex",
            install_command=(
                "if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {"
                " Write-Output 'Node.js is needed first; installing it.';"
                " winget install --id OpenJS.NodeJS.LTS -e --silent --accept-package-agreements --accept-source-agreements;"
                " $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') };"
                " npm install -g @openai/codex"),
            needs_account="your ChatGPT account; sign in with codex login"),
)

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


def _ask(executable: str, *argv: str, keep_lines: int = 400) -> str:
    """Run a CLI's own self-description and come back, whatever it does.

    **`subprocess.run(timeout=…)` is not enough on Windows**, and that is not
    a theory either: `locate` once matched an unrelated Electron application
    called OpenCode, Kriko ran it with `--help`, and the probe never
    returned. `run` kills the process it started when the timeout fires and
    then calls `communicate()`, which waits for the *pipes* to close — and a
    GUI app's surviving children hold them open forever. The timeout expires
    and the function still does not come back.

    So: `Popen`, a timer that kills the whole tree, and pipes drained in
    threads. Same three pieces as `_stream`, for the same reason, one
    question smaller — a process asked what flags it has must always be
    answerable, because every screen that lists the planes waits on it.

    `""` on anything going wrong, which reads as "said nothing": a probe is
    never why a plane is unavailable.

    `keep_lines` bounds what is kept, the *last* lines: a `--help` never needs
    more than the default, and a listing does (B158: `opencode models` prints
    426 lines on the reader's machine, and the first 27 were dropped).
    """
    out: list[str] = []
    try:
        proc = subprocess.Popen(  # noqa: S603 - fixed executable, no shell
            [executable, *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env={**child_env(extra_dirs=(str(Path(executable).parent),) if os.path.isabs(executable) else ()), **CHILD_ENCODING_ENV},
            start_new_session=True,
            startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001 — a CLI that will not start declares nothing
        return ""
    killed = threading.Event()

    def _give_up() -> None:
        killed.set()
        HarnessResearcher._kill_tree(proc)

    timer = threading.Timer(HELP_TIMEOUT_SECONDS, _give_up)
    timer.start()
    reader = threading.Thread(
        target=HarnessResearcher._drain, args=(proc.stdout, out, keep_lines), daemon=True
    )
    reader.start()
    try:
        proc.wait(timeout=HELP_TIMEOUT_SECONDS * 2)
    except Exception:  # noqa: BLE001
        HarnessResearcher._kill_tree(proc)
    finally:
        timer.cancel()
    # Bounded: the drain thread may still be running against a pipe held open
    # by a child nothing can reach, and this must return regardless.
    reader.join(timeout=1.0)
    try:
        if proc.stdout is not None:
            proc.stdout.close()
    except Exception:  # noqa: BLE001
        pass
    return "" if killed.is_set() else "".join(out)


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
    text = _ask(executable, "--help")
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


#: `provider/model` lines, the shape `opencode models` prints. The model part
#: may hold slashes of its own (`openrouter/anthropic/claude-opus-4.8` is one
#: id, and `--model` takes it whole) but may not start with one, so a URL in a
#: status line is not a row. Anything else on a line (headers, counts, blank
#: lines) is not a model and is dropped.
_MODEL_LINE = re.compile(r"^\s*([^/\s]+/[^/\s#][^\s#]*?)\s*(?:#.*)?$")


def _model_id(line: str) -> str:
    """The model one line of `<cli> models` names, or `""` when it is not a row.

    Two row shapes exist in the CLIs this asks, and both are read by their
    structure: `provider/model` (opencode), and `id<TAB>display name` (agy).
    A status line has neither: `Fetching available models...` is prose with no
    tab and no slash, and it reaches this parser because `_ask` merges the
    CLI's stderr into its stdout. No word is listed as "not a model", so the
    next status line a CLI grows is refused by the same rule.
    """
    ident, tab, label = line.strip("\r\n").lstrip().partition("\t")
    if tab and label.strip() and ident and not any(ch.isspace() for ch in ident):
        return ident
    match = _MODEL_LINE.match(line)
    return match.group(1) if match else ""


#: A name quoted in help text: `'opus'`, `"claude-fable-5"`.
_QUOTED = re.compile(r"""['"`]([A-Za-z0-9][\w.:/\[\]-]*)['"`]""")

#: How long a listing is trusted. A CLI's model list changes when the CLI is
#: updated or the reader signs in, not between two clicks, and asking it costs
#: a process start that `agy models` stretches to seconds — which, paid on
#: every read *and every save* of the Agents screen, is what made choosing a
#: model feel like the app had hung. An empty answer is trusted for less: it
#: is usually "not signed in yet", which the reader is about to fix.
MODELS_TTL = 600.0
_MODELS_TTL_EMPTY = 60.0
#: The most lines of a `models` listing kept. The listing is bounded by the
#: probe's own timeout; this stops a CLI that never stops printing.
_LISTING_LINES = 20_000
_MODELS: dict[tuple[str, str, float], tuple[float, list[str]]] = {}
_MODELS_LOCK = threading.Lock()
_ASKING: dict[str, threading.Lock] = {}

# Claude's --model help quotes examples, not its complete model catalogue.
# Keep the documented fast alias and an explicit Haiku 5.5 pin selectable.
# Full IDs are accepted by --model; the CLI/account decides availability.
# https://code.claude.com/docs/en/model-config (Haiku 5.5: CLI >= 2.1.293).
CLAUDE_FAST_MODELS = ("claude-haiku-5-5", "haiku")


def _from_help(text: str, flag: str) -> list[str]:
    """The names the `flag` entry of a `--help` quotes, in the order it quotes them.

    Only that entry: the rest of the help quotes other things (`'text'`,
    `'stream-json'`), and a format name offered as a model is the kind of
    wrong that reads as right. The entry runs from the flag's own line to the
    next line that starts another option.
    """
    out: list[str] = []
    lines = text.splitlines()
    for at, line in enumerate(lines):
        if not re.match(rf"^\s*(?:-\w,\s*)?{re.escape(flag)}\b", line):
            continue
        block = [line]
        for following in lines[at + 1:]:
            if re.match(r"^\s*-", following) or not following.strip():
                break
            block.append(following)
        joined = " ".join(block)
        names = _QUOTED.findall(joined)
        if not names:
            # "(low, medium, high, xhigh, max)": a bare parenthesised list.
            for group in re.findall(r"\(([^()]*,[^()]*)\)", joined):
                names += [w for w in re.split(r"\s*(?:,|\bor\b)\s*", group)
                          if re.fullmatch(r"[A-Za-z0-9][\w.:/-]*", w)]
        for name in names:
            if name not in out:
                out.append(name)
        break
    return out

def efforts_for(one: Harness) -> list[str]:
    """The effort levels this machine's CLI will accept, or `[]`.

    Gated on the flag being *declared*, not on the roster row naming it: the
    levels are documented in the same `--help` the flag is, so a build old
    enough to lack `--effort` should offer no levels rather than a dropdown
    whose every entry fails. `[]` means the screen hides the control, which is
    the honest rendering of "this CLI has no such dial".
    """
    if one.unusable or not one.effort_flag:
        return []
    if one.protocol in {"vibe", "codex"}:
        return list(one.effort_choices)
    executable = locate(one)
    if not executable:
        return []
    if one.effort_flag not in declared(executable):
        return []
    # The CLI's own list first — `claude --help` prints "(low, medium, high,
    # xhigh, max)" beside the flag — and the row's copy of it only where the
    # help names none, so a build that adds a level offers it the day it ships.
    return _from_help(helptext(executable), one.effort_flag) or list(one.effort_choices)


def settle_effort(one: Harness, model: str, effort: str) -> tuple[str, str]:
    """`(model, effort)` this CLI will take together (B154).

    `agy` spells effort twice: as `--effort` and as the tail of its model ids
    (`gemini-3.8-flash-medium`). Asked for both, it refuses the pair — "--model
    gemini-3.8-flash-medium conflicts with --effort=low" — which is how every
    Antigravity quick look died, since the quick look asks for `low` on top of
    whichever model the reader picked. A model whose tail is one of the CLI's
    own levels already carries an effort, so the flag goes and the effort moves
    into the id: the `-low` sibling when the CLI lists one, otherwise the
    reader's model as picked. Both lists are the CLI's (`--help`, `agy
    models`); a CLI whose ids carry no level passes through untouched.

    **A tail that only looks like a level is not one.** An id is read as
    carrying its effort only when the CLI lists a sibling that differs from it
    by another level: `gemini-3.1-pro-high` beside `gemini-3.1-pro-low` does,
    a lone `…-codex-max` on a CLI that one day adds `max` to its dial does not,
    and keeps its flag. An empty list (a cold cache) drops the flag rather than
    risk the refusal: a run at the reader's own level is slower, not failed.
    """
    base, _, tail = model.rpartition("-")
    levels = efforts_for(one) if base and effort else []
    if tail not in levels:
        return model, effort
    listed = models_for(one)
    if listed and not ({f"{base}-{level}" for level in levels} - {model}) & set(listed):
        return model, effort
    sibling = f"{base}-{effort}"
    return (sibling if sibling in listed else model), ""


def with_refused_page(prompt: str) -> str:
    """`prompt`, saying what a refused page means, once (B154).

    Every brief a CLI is handed says it, whichever door wrote the brief: the
    research, quick-look and pack-author briefs place it themselves, and review
    found amend, disambiguate and site-register briefs that did not. Said at
    the one door every CLI run passes, a brief written next month cannot
    forget it.
    """
    if REFUSED_PAGE in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{REFUSED_PAGE}\n"


def reader_config() -> dict:
    """The per-run MCP config that names the page reader and nothing else."""
    return {"mcpServers": {READER_SERVER: {"type": "http", "url": READER_URL}}}


def reader_tools(one: Harness) -> list[str]:
    """The reader's tools, as this CLI's allowlist spells them."""
    if one.reader is None:
        return []
    return [one.reader.tool.format(server=READER_SERVER, tool=tool) for tool in READER_TOOLS]


def _with_grant(args: tuple[str, ...], flag: str, tools: list[str]) -> tuple[str, ...] | None:
    """`args` with `tools` added to the value of allowlist `flag`, or `None`.

    `None` when the vector carries no such allowlist: a reader with nothing to
    be granted through would be a config whose every read is a permission
    prompt a headless run cannot answer, so it is not attached at all.
    """
    if flag not in args or args.index(flag) + 1 >= len(args):
        return None
    at = args.index(flag) + 1
    return (*args[:at], ",".join([*args[at].split(","), *tools]), *args[at + 1:])


def reader_attachable(one: Harness, supported: frozenset[str] | None = None) -> bool:
    """Whether this machine's copy of `one` can be handed the page reader.

    Three facts, each asked rather than assumed: the row says it takes a
    per-run MCP config at all, this build's own `--help` declares the flag, and
    the row's vector has an allowlist for the reader's tools to join. A reader
    on an older build keeps the plane and loses the reader (B154's rule for
    every flag here).
    """
    if one.reader is None or one.unusable:
        return False
    supported = declared(locate(one) or one.executable) if supported is None else supported
    return one.reader.config_flag in supported and all(
        _with_grant(vector, one.reader.grant_flag, []) is not None
        for vector in (one.args, one.plain_args) if vector
    )


def page_reader_note(tools: list[str]) -> str:
    """What the agent is told about the page reader, when this run has one.

    Said only for a run the reader is attached to (`_run`): a note about a tool
    that is not there would send the agent looking for it. It is an exception
    to `REFUSED_PAGE` and sits beside it, so the two are read together, and it
    ends on the way out if the reader is refused as well.
    """
    names = " or ".join(f"`{name}`" for name in tools)
    return (
        f"The one exception is this run's page reader, the {names} tool: when a "
        "fetch is refused, read that page once through it, passing "
        f"`maxCharacters` of {READER_PAGE_CHARS}, and quote from what it returns. "
        "A refused fetch opened nothing, so it does not count toward the pages "
        "you may read; the read through the reader does. If the reader is "
        "refused as well, or that tool is not among yours, take the same "
        "question to another source."
    )


def with_page_reader(prompt: str, tools: list[str]) -> str:
    """`prompt`, with `page_reader_note` beside its refused-page line, once."""
    note = page_reader_note(tools)
    if note in prompt:
        return prompt
    if REFUSED_PAGE in prompt:
        return prompt.replace(REFUSED_PAGE, f"{REFUSED_PAGE} {note}", 1)
    return f"{prompt.rstrip()}\n\n{note}\n"


def _from_models_command(one: Harness, executable: str) -> list[str]:
    # Through `_ask` for the reason `helptext` is: this runs a binary
    # `locate` only *guessed* at, and a wrong guess must cost a dropdown
    # rather than the screen. The exit code is not read — a CLI that printed
    # a list and then exited non-zero over a telemetry ping has still
    # answered the question, and the line filter below rejects anything that
    # is not a model name.
    out: list[str] = []
    # The whole listing: it is not `--help`, and a long one lost its head to
    # the default bound.
    for line in _ask(executable, "models", keep_lines=_LISTING_LINES).splitlines():
        name = _model_id(line)
        if name and name not in out:
            out.append(name)
    return out


def _stamp(executable: str) -> float:
    """When this binary last changed — an update is a new cache entry."""
    try:
        return os.stat(executable).st_mtime
    except OSError:
        return 0.0


def models_for(one: Harness, *, fresh: bool = False, behind: bool = False) -> list[str]:
    """The models this machine's copy of the CLI offers, or `[]`.

    Asked, never assumed: `agy models` and `opencode models` list what is
    actually installed and authenticated, and `claude --help` names the
    aliases its own build knows — a list written here would have gone stale
    the day a model shipped, which is exactly how it did. Anything failing —
    missing CLI, slow answer, unparseable output — reads as "no list", and the
    dropdown degrades to a free-text field with the hint. A model list must
    never be why a run does not start.

    Cached per binary (path and modification time, so an updated CLI is asked
    again) for `MODELS_TTL`; `fresh` asks regardless. Past the TTL the old
    list is served and the ask runs `behind` (B152.7): an expired cache used
    to make the next Settings visit wait ~7 s for every CLI to answer.
    """
    if one.unusable or not one.model_source:
        return []
    executable = locate(one)
    if not executable:
        return []
    key = (one.id, executable, _stamp(executable))
    with _MODELS_LOCK:
        cached = _MODELS.get(key)
    if cached and not fresh and not behind:
        at, names = cached
        if time.monotonic() - at < (MODELS_TTL if names else _MODELS_TTL_EMPTY):
            return list(names)
        if names:
            threading.Thread(
                target=lambda: models_for(one, behind=True),
                name=f"kriko-models-{one.id}", daemon=True,
            ).start()
            return list(names)
    # One ask per CLI at a time, but a reader's own request never queues
    # behind one already in flight: `warm_models()` starts this same probe on
    # a background thread at startup precisely so the first visit to the
    # Agents screen does not pay its cost, and a request that blocked on this
    # lock while that thread held it paid the identical ~2s anyway — the
    # warm-up existed and did nothing for that first click. So a request that
    # finds the lock held serves whatever is cached (possibly `[]`, on a CLI
    # never asked before) rather than waiting for the in-flight ask, which
    # will populate the cache for the *next* read regardless.
    asking_new = threading.Lock()
    with _MODELS_LOCK:
        asking = _ASKING.setdefault(one.id, asking_new)
    # `fresh` is always an explicit ask (a reader pressing Re-ask) and waits
    # for a real answer. An ordinary read does not: it takes whatever is
    # cached rather than queueing behind the in-flight probe.
    if not asking.acquire(blocking=fresh):
        with _MODELS_LOCK:
            cached = _MODELS.get(key)
        return list(cached[1]) if cached else []
    try:
        with _MODELS_LOCK:
            cached = _MODELS.get(key)
        if cached and not fresh:
            at, names = cached
            if time.monotonic() - at < (MODELS_TTL if names else _MODELS_TTL_EMPTY):
                return list(names)
        if one.model_source == "vibe-config":
            try:
                config = tomllib.loads((Path.home() / ".vibe" / "config.toml").read_text(encoding="utf-8"))
                names = list(dict.fromkeys(str(row.get("alias") or row.get("name")) for row in config.get("models", []) if isinstance(row, dict) and (row.get("alias") or row.get("name"))))
            except (OSError, ValueError):
                names = []
        elif one.model_source == "codex-cache":
            try:
                cached_models = json.loads((Path.home() / ".codex" / "models_cache.json").read_text(encoding="utf-8"))
                names = [row["slug"] for row in cached_models.get("models", [])
                         if isinstance(row, dict) and row.get("slug") and row.get("visibility", "list") == "list"]
            except (OSError, ValueError, TypeError):
                names = []
        elif one.model_source == "help":
            # `--help` is cached for the process, and a binary that changed
            # under it (an update) or a reader pressing Re-ask needs it read
            # again — its flags as much as its names.
            with _MODELS_LOCK:
                changed = any(k[:2] == key[:2] and k != key for k in _MODELS)
            if fresh or changed:
                _HELP.pop(executable, None)
                _DECLARED.pop(executable, None)
            names = _from_help(helptext(executable), one.model_flag)
            if one.id == "claude-code":
                names = list(dict.fromkeys((*CLAUDE_FAST_MODELS, *names)))
        else:
            names = _from_models_command(one, executable)
        with _MODELS_LOCK:
            _MODELS[key] = (time.monotonic(), names)
        return list(names)
    finally:
        asking.release()


def models_note(one: Harness, names: list[str]) -> str:
    """One line for a pick that has no list to show, or `""` (B158).

    "A CLI that lists no models says so, rather than showing an empty pick."
    Said only where it is known: a CLI with no listing to read (Vibe) never
    lists, and one that was asked and named nothing has listed nothing. One
    not yet asked, because the warm-up is still running, has said nothing
    either way, so this stays silent rather than claim what nobody checked.
    """
    if names or one.unusable:
        return ""
    if not one.model_source:
        return "This CLI does not list its models"
    executable = locate(one)
    with _MODELS_LOCK:
        asked = any(k[:2] == (one.id, executable) for k in _MODELS)
    return "This CLI listed no models" if asked else ""


def models_for_each(harnesses: list[Harness], *, fresh: bool = False) -> dict[str, list[str]]:
    """`models_for` over several CLIs at once — concurrently, because each is a
    process start and a screen showing three harnesses should wait for the
    slowest one, not for their sum."""
    if not harnesses:
        return {}
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(harnesses)) as pool:
        lists = pool.map(lambda one: models_for(one, fresh=fresh), harnesses)
        return dict(zip((one.id for one in harnesses), lists, strict=True))


def warm_models() -> None:
    """Ask every installed CLI for its list once, in the background, so the
    first visit to the Agents screen does not pay for it."""
    threading.Thread(
        target=lambda: models_for_each(available()), name="kriko-models-warm", daemon=True,
    ).start()


def scale_args(one: Harness, *, max_documents: int = 0, budget_usd: float = 0.0,
               supported: frozenset[str] | None = None) -> list[str]:
    """The ceilings this CLI can be told about, for this run.

    Separate from `command_for` because it answers a different question —
    that one asks *can this vector start*, this one asks *how much of the
    reader's account may it spend* — and because a caller with no scale (the
    CLI's own path, a pack-authoring run) should be able to skip it entirely
    rather than pass two zeroes through three layers.

    A flag this machine's CLI does not declare is dropped rather than
    refused: losing a ceiling is a worse run, and losing the plane over it
    would be the `--verbose` mistake again. Zero means "no ceiling asked
    for", which is how every caller that has nothing to say says nothing.
    """
    executable = locate(one) or one.executable
    supported = declared(executable) if supported is None else supported
    out: list[str] = []
    if budget_usd and one.budget_flag and one.budget_flag in supported:
        out += [one.budget_flag, f"{float(budget_usd):.2f}"]
    if max_documents and one.turns_flag and one.turns_flag in supported:
        turns = max(4, int(max_documents) * max(1, one.turns_per_source))
        out += [one.turns_flag, str(turns)]
    return out


def command_for(one: Harness, *, model: str = "", effort: str = "",
                max_documents: int = 0, budget_usd: float = 0.0,
                reader_config: str = "") -> list[str]:
    """The vector this machine will actually run — `args` plus what it takes.

    A function rather than a line inside `_run` because the gate that matters
    runs the *real* CLI against it: every earlier check here asserted the
    shape of `args` and none asserted the CLI would accept them, which is how
    B92 shipped a plane that could not start at all. A test can only judge the
    vector if the vector has a name.

    `reader_config` is the path of this run's page-reader config (B155). It is
    attached only where the row declares a reader, this machine's `--help`
    declares the config flag, and the vector has an allowlist to grant the
    reader's tools through — otherwise the vector is exactly what it was.
    """
    executable = locate(one) or one.executable
    if one.protocol == "codex":
        return [executable, *one.args, "--ignore-user-config", "--ignore-rules",
                "-c", 'approval_policy="never"', "-c", 'web_search="live"',
                "-c", "features.shell_tool=false",
                *(["--model", model] if model else []),
                *(["-c", f'model_reasoning_effort="{effort}"'] if effort else [])]
    supported = declared(executable)
    args = one.args
    if one.needs_in_help and one.plain_args:
        if one.needs_in_help not in helptext(executable):
            args = one.plain_args
    missing = set(one.required) - supported
    if one.unusable or missing:
        raise NoHarness(one.unusable or f"{one.label} lacks required flags: {', '.join(sorted(missing))}")
    if model and not one.model_flag and not one.model_env:
        raise NoHarness(f"{one.label} has no verified per-run model switch — model choices for it are refused, never silently run as the default")
    if model and one.model_flag and not one.model_unlisted and one.model_flag not in supported:
        raise NoHarness(f"{one.label} does not declare per-run model selection")
    # Refused rather than dropped, on the same reasoning as the model above: a
    # reader who asked for `low` and silently got the CLI's default has been
    # billed for a choice they did not make, and the run looks identical.
    if effort and one.protocol != "vibe" and (not one.effort_flag or one.effort_flag not in supported):
        raise NoHarness(
            f"{one.label} has no per-run effort switch on this machine — "
            f"effort choices for it are refused, never silently run as the default")
    attach: list[str] = []
    reader = one.reader
    if reader_config and reader is not None and reader_attachable(one, supported):
        args = _with_grant(args, reader.grant_flag, reader_tools(one)) or args
        attach = [reader.config_flag, reader_config]
    return [executable, *args, *(f for f in one.preferred if f in supported),
            *(part for flag, value in one.preferred_values if flag in supported
              for part in (flag, value)),
            *attach,
            *([one.model_flag, model] if model and one.model_flag else []),
            *([one.effort_flag, effort] if effort and one.protocol != "vibe" else []),
            *scale_args(one, max_documents=max_documents,
                        budget_usd=budget_usd, supported=supported)]


# ── The output contract ──────────────────────────────────────────────────────

#: Appended to the pack's brief. The brief already says what to look for and
#: what is worth keeping — it is written for an agent holding Kriko's MCP
#: tools, so the only thing it needs replacing is the *reporting* step.
CONTRACT = """
## What you may use (this run)

**Only the web search and web fetch tools.** Do not read files, list
directories, run shell commands, or look at the working directory — it is an
empty temporary folder created for this run and there is nothing in it. This
is a reading task about the world, not a task about a codebase, and the usual
first move of orienting yourself in the workspace is wasted here.

That is not advice. On some of the command-line agents this runs on, a tool
call that is refused **ends the whole run with an empty answer** — and the
refusal is automatic, because nothing is watching to approve it. One
`ls`-shaped reflex therefore costs the entire run, on an account somebody
pays for, and returns nothing at all. Search, read pages, and report.

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

def budget_clause(max_documents: int) -> str:
    """How much reading this run is worth, said before the agent starts.

    The brief says what to look for; nothing said *how much*. So the dial the
    reader set — three sources, or fifteen — reached the agent as nothing at
    all, and the plane whose whole promise is "it costs you only what your
    subscription already costs" spent the same amount at every setting.

    Written as a ceiling with a floor under it, because the failure to avoid
    is an agent that reads two pages, finds nothing, and reports an empty
    findings list as though the subject were clean. A budget is permission to
    stop early, not an instruction to.

    `""` for zero, which reads as "nobody set one" — the CLI path's case, and
    every caller's before the dial existed.
    """
    if not max_documents:
        return ""
    return (
        "\n## How much to read (this run)\n\n"
        f"Read **at most {max_documents} source page(s)** and run at most "
        f"{max(2, max_documents)} searches. This is a ceiling the reader set, "
        "and it is the whole cost of this run to them — stop when you reach "
        "it, even if the next search looks promising, and say so in your "
        "reply rather than going over.\n\n"
        "Spend the budget on the *best* sources rather than the first ones: "
        "one page you read properly and quoted is worth more here than three "
        "skimmed. If the budget runs out before you are confident, report "
        "what you have and say what you would have read next — a short honest "
        "run is a result, and an invented claim outlives you in the pack.\n"
    )


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
        if parsed.get("event") == "result" and isinstance(parsed.get("result"), dict):
            return parsed["result"]
        return parsed
    if isinstance(parsed, list):
        objects = [item for item in parsed if isinstance(item, dict)]
        results = [item for item in objects if item.get("type") == "result"]
        if results:
            return results[-1]
        return objects[-1] if objects else {}
    last: dict = {}
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
        # Antigravity's print mode speaks a different dialect: the envelope
        # is `{"event": "result", "result": {...}}`, with the reply under
        # `response` and usage beside it. Unwrapped here so `_meter` and
        # `_unwrap` below can read either CLI without knowing which answered.
        if one.get("event") == "result" and isinstance(one.get("result"), dict):
            return one["result"]
        if one.get("event") is not None:
            continue
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
    denied = envelope.get("denied_actions")
    if isinstance(denied, list) and denied:
        names = []
        for item in denied:
            name = item.get("display_name") if isinstance(item, dict) else str(item)
            if name and name not in names:
                names.append(str(name))
        parts.append(
            "headless mode cannot approve tool permissions, and this run needed "
            + ", ".join(names)
        )
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

#: How long a conversational run may say *nothing at all* before it is
#: abandoned and retried the ordinary way.
#:
#: The other half of the B125 scar. That failure was a prompt that never
#: crossed the `cmd.exe` shim, and its cost was not the loss — it was that the
#: CLI shrugged and ran with no prompt, so the reader paid for a run that
#: researched nothing and read like a success. Streaming input cannot do that:
#: with no message there is nothing to run, so the child simply waits. Which
#: would make the same broken pipe a twenty-minute hang instead, and that is
#: what this number is for. `claude -p --output-format stream-json` prints its
#: `system`/`init` event before it makes an API call, so a minute of total
#: silence is not a slow model, it is a pipe that did not arrive.
CONVERSATION_START_SECONDS = 60.0

#: How long a turn that ended on a question holds the pipe open for an answer.
#: The worker is single, so this is time every queued job waits too: long
#: enough to read a question and type a word, not long enough to go and look.
ANSWER_WAIT_SECONDS = 180.0

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

#: How long a run may print nothing before its log says it is still alive.
#: Reported as "they seem like they are stuck" (B146): `claude -p` in
#: stream-json emits a message only once it is whole, so one long answer is
#: minutes of an empty log on a run that is working normally. The line is the
#: difference between "working" and "hung" that the reader could not see.
HEARTBEAT_SECONDS = 30.0

#: Events that are machinery rather than actions — session bookkeeping, the
#: partial-token frames, the command list. Named rather than filtered by
#: "anything I do not recognise", so a *new* event type shows up as a line
#: nobody wrote a translation for instead of silently disappearing.
QUIET_EVENTS = frozenset(
    {"stream_event", "active_goal", "autocompact_state", "rate_limit_event"}
)


def _is_result(line: str) -> bool:
    """Whether one stream-json line is the event that ends a turn."""
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        return False
    return isinstance(event, dict) and event.get("type") == "result"


def _asks(line: str) -> bool:
    """Whether a turn's `result` ended on a question to the reader.

    Deliberately literal. A question mark is the one signal every model gives
    when it wants something back, and guessing at intent beyond that would
    hold the job worker for runs that were simply done.
    """
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        return False
    text = event.get("result") if isinstance(event, dict) else None
    return isinstance(text, str) and text.rstrip().endswith("?")


def _short(text: str, limit: int = 160) -> str:
    """One line, trimmed. A log line that wraps four times is not a log line."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _tool_line(name: str, args: dict | None) -> str:
    """What one tool call was, in the reader's words rather than the API's.

    `SEARCH_TOOLS` is the whole grant, so there are two shapes worth naming
    and a general one for anything a future grant adds. It reads the argument
    the tool is *about* — the query, the URL — because "WebSearch" on its own
    tells a reader watching the log nothing they did not already assume.
    """
    args = args if isinstance(args, dict) else {}
    query = args.get("query") or args.get("q")
    url = args.get("url")
    # The page reader (B155) takes a list, under whichever server name the
    # CLI's allowlist spells in front of the tool. The log names it as what it
    # is, because "read through the page reader" is the line that shows a
    # refused page was not fetched a second time.
    if any(name.endswith(tool) for tool in READER_TOOLS):
        urls = args.get("urls")
        urls = [str(one) for one in urls] if isinstance(urls, list) else [str(url or "")]
        return f"read through the page reader {_short(', '.join(u for u in urls if u), 120)}".strip()
    # Folded, because the same two tools are spelled four ways across these
    # CLIs — `WebSearch`/`WebFetch`, `web_search`/`web_fetch` — and a reader
    # watching the log should not be able to tell which CLI is running from
    # whether the line says "fetched" or prints a function name.
    plain = name.replace("_", "").replace("-", "").lower()
    if plain == "websearch" and query:
        return f'searched "{_short(query, 120)}"'
    if plain == "webfetch" and url:
        return f"fetched {_short(url, 120)}"
    detail = query or url or ""
    return f"{name} {_short(detail, 100)}".strip()


def _narrate_agy(event: dict) -> str:
    """One Antigravity print-mode event, as a job-log line — or `""`.

    Verified against the real CLI's `--output-format stream-json`: `init`
    carries the session, `step_update` carries each finished step (a tool call
    with its arguments, a model reply, or a tool error), and `result` carries
    the reply with usage. Anything else is machinery.
    """
    kind = event.get("event")
    if kind == "init":
        return "started"
    if kind == "step_update":
        step = event.get("step_update")
        if not isinstance(step, dict):
            return ""
        if step.get("step_type") == "tool":
            info = step.get("tool_info")
            name = ""
            detail = ""
            if isinstance(info, dict):
                name = str(info.get("name") or info.get("tool_name") or "")
                params = info.get("parameters")
                if isinstance(params, dict):
                    detail = str(
                        params.get("Url") or params.get("url")
                        or params.get("query") or params.get("prompt") or ""
                    )
            name = name or str(step.get("tool_name") or "")
            said = f"{name} {_short(detail, 100)}".strip()
            # One line per tool call, not two. The CLI reports each step
            # twice — ACTIVE when it starts, DONE when it finishes — with the
            # same name and the same arguments, so narrating both printed
            # every search the agent ran immediately below itself.
            if step.get("state") == "ACTIVE":
                return ""
            if step.get("state") == "ERROR":
                error = info.get("error") if isinstance(info, dict) else None
                message = ""
                if isinstance(error, dict):
                    message = str(error.get("message") or "")
                return "a tool call failed: " + _short(
                    message or said or "unknown tool error", 160)
            return said
        if step.get("step_type") == "agent_response":
            # Nothing, on purpose: `text_delta` is a *fragment* of the reply,
            # a few characters wide, and a line of the job log is a whole
            # thought. `HarnessResearcher._say` owns the joining up, because
            # it is the only thing here with somewhere to keep a buffer.
            return ""
        return ""
    if kind == "result":
        result = event.get("result")
        if not isinstance(result, dict):
            return ""
        said = "finished"
        turns = result.get("num_turns")
        if isinstance(turns, int) and not isinstance(turns, bool):
            said += f" after {turns} turn(s)"
        tokens = _tokens(result.get("usage") or {})
        if tokens:
            said += f", {tokens} tokens on the subscription's account"
        return said
    return ""


def _narrate_vibe(event: dict) -> str:
    """One Mistral Vibe history entry, as a job-log line — or `""`.

    Its stream is the session's own history rather than a feed of events, so
    the three entry types worth a line are the three a reader would watch
    for: what the agent said, what it ran, and what broke. Read off
    `vibe/app_server/models.py` (`PublicMessageEntry`, `PublicEffectEntry`),
    camelCase on the wire.

    Only *completed* entries. An entry is emitted again on every update while
    it generates, so narrating the in-flight ones would fill the job log with
    the same sentence growing one word at a time.
    """
    status = str(event.get("generationStatus") or "").lower()
    if status and status != "completed":
        return ""
    kind = event.get("type")
    if kind == "message":
        if event.get("role") != "assistant":
            return ""
        parts = [
            str(block.get("text") or "")
            for block in event.get("content") or ()
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return _short(" ".join(one for one in parts if one.strip()), 200)
    if kind == "effect":
        title = _short(str(event.get("title") or ""), 140)
        state = str(event.get("state") or "").lower()
        if state in ("failed", "error"):
            return "a tool call failed: " + (title or "unknown tool error")
        return title
    return ""


def _narrate_copilot(event: dict) -> str:
    """One GitHub Copilot CLI event, as a job-log line — or `""`.

    Its stream is `{"type": "<noun>.<verb>", "data": {...}}`, and almost all
    of it is bookkeeping: the MCP and skill inventories are printed three
    times before the first token, and every sentence arrives twice — once as
    a run of `assistant.message_delta` frames and once whole, as
    `assistant.message`. So this reads the whole ones and drops the frames,
    which is the same choice `_narrate_vibe` makes for the same reason.

    The failure lines are worth as much as the actions. `model.call_failure`
    is how "the requested model is not supported" reaches a reader — the CLI
    retries it twice, ends the turn and exits 1 — and without it the run
    reads as a silent minute followed by an exit code.
    """
    kind = str(event.get("type") or "")
    data = event.get("data")
    data = data if isinstance(data, dict) else {}
    if kind == "assistant.message":
        lines = [
            _tool_line(str(request.get("name") or ""), request.get("arguments"))
            for request in data.get("toolRequests") or ()
            if isinstance(request, dict)
        ]
        said = str(data.get("content") or "").strip()
        if said:
            lines.append(_short(said, 200))
        return "; ".join(one for one in lines if one)
    if kind == "model.call_failure":
        return "the model call failed: " + _short(
            str(data.get("errorMessage") or data.get("statusCode") or ""), 160
        )
    if kind == "session.error":
        return "a tool call failed: " + _short(str(data.get("message") or ""), 160)
    if kind == "session.tools_updated":
        model = str(data.get("model") or "").strip()
        return f"started {model}" if model else ""
    if kind == "result":
        return "finished" if not event.get("exitCode") else ""
    return ""


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
    if event.get("event") is not None:
        return _narrate_agy(event)
    # Vibe's entries are the only ones carrying a session id and a generation
    # status, which is a cheaper tell than threading the harness through every
    # caller of this function — and a wrong guess here costs a log line, never
    # a run.
    if event.get("sessionId") is not None and event.get("generationStatus") is not None:
        return _narrate_vibe(event)
    # Copilot's events are the only ones whose `type` is dotted and whose
    # payload sits under `data` — the same kind of cheap tell, and a wrong
    # guess here still costs a log line rather than a run. `result` is the
    # one type it shares with Claude Code's stream, and that one carries no
    # `data`, so it falls through to the branch below that already reads it.
    if isinstance(event.get("type"), str) and "." in event["type"] and "data" in event:
        return _narrate_copilot(event)
    kind = event.get("type")
    if kind in QUIET_EVENTS:
        return ""
    if kind == "system":
        if event.get("subtype") != "init":
            return ""
        model = str(event.get("model") or "").strip()
        said = f"started {model}".strip() if model else "started"
        # Which MCP servers came up, from the CLI's own init line. The page
        # reader that never loaded looks exactly like one that was never
        # asked, and this is the only place the difference is visible.
        servers = event.get("mcp_servers")
        up = [
            f"{one.get('name')} {one.get('status')}".strip()
            for one in servers if isinstance(one, dict) and one.get("name")
        ] if isinstance(servers, list) else []
        return "; ".join([said, *up])
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
     "{label}'s account has no headroom right now. Wait for the reset "
     "the message names, or switch to another agent on the Agents screen."),
    (("not logged in", "please run /login", "unauthorized", "authentication",
      "invalid api key", "oauth"),
     "{label} is not logged in, and only you can log it in -- no API call can "
     "do it on its behalf. Open the terminal in this app (Ctrl+`), run "
     "`{cli}`, and follow its login prompt. Then press "
     "this again. Kriko Console in your Start menu opens the same shell "
     "without the app."),
    (("credit balance", "billing", "payment"),
     "the account behind the CLI cannot pay for this run."),
    (("error_max_turns",),
     "the agent ran out of turns before it reported. This is Kriko's to fix, "
     "not yours -- please send the log."),
    (("enoent", "not recognized", "cannot find the path"),
     "the CLI could not start. Check that it runs in a terminal; if it is "
     "installed somewhere unusual, set KRIKO_HARNESS_DIRS to its folder. "
     "The Agents screen names the binary Kriko found and where it looked."),
    (("cannot approve tool permissions", "permission check failed",
       "denied_actions", "request-review"),
     "headless mode cannot answer a permission prompt, so the tool was "
     "auto-denied. Add an allow rule for it under permissions.allow in the "
     "CLI's own settings file, or run the research on another plane from "
     "the Agents screen. Never use --dangerously-skip-permissions for this: "
     "it approves every tool, not just the web search this run needs."),
)


def _hint(reason: str, harness: "Harness | None" = None) -> str:
    """The next action for a failure class Kriko recognises, or nothing.

    A reason with no action attached is only half of what a reader needs.
    `Claude Code exited 1: error_during_execution` says what happened; it
    does not say whether to wait, log in, or report it — and a reader who has
    now watched this button fail in two releases has earned the second half.

    Named for the CLI that failed (B146): the login hint said "run `claude`"
    under a Mistral Vibe failure, which sends the reader to the wrong tool.
    """
    low = (reason or "").lower()
    label = harness.label if harness else "The CLI"
    cli = Path(harness.executable).stem if harness else "the CLI"
    for needles, hint in HINTS:
        if any(needle in low for needle in needles):
            return hint.format(label=label, cli=cli)
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

    def __init__(self, harness: Harness, *, timeout: float = TIMEOUT_SECONDS,
                 model: str = "", effort: str = ""):
        self.requested_model = model
        #: How hard to think, this run. Beside the model rather than folded
        #: into it: the two are chosen independently, and a survey run is the
        #: same model at a lower effort far more often than it is a different
        #: model.
        self.requested_effort = effort
        #: One line for the run's log when `settle_effort` changed the
        #: reader's pick (B154), set by `providers.harness_researcher`: a run
        #: on `-low` where the reader chose `-medium`, or on `-high` with no
        #: effort flag, should say so rather than be quietly slower or faster.
        self.effort_settled = ""
        self._run_env: dict[str, str] = {}
        self._run_cwd: str | None = None
        #: The path of this run's page-reader config while a run has one (B155).
        self._reader_config = ""
        self.harness = harness
        self.timeout = timeout
        #: The scale, as the CLI will be told it. Set from the task by
        #: `gather`, and settable directly by a caller with no task —
        #: `tasks.pack_author` is one, and a pack-authoring run has a budget
        #: too. `0` on either means "no ceiling asked for", which is what
        #: every caller said before the dial reached this far.
        #:
        #: They live on the instance rather than travelling as arguments
        #: because `ask()` and `gather()` are two entry points to one spawn,
        #: and a ceiling that applied to only one of them would be a ceiling
        #: the reader could not predict.
        self.max_documents = 0
        self.budget_usd = 0.0
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
        #: What the reader has said to this run since it was last asked.
        #:
        #: Set beside `check_cancelled` and read in the same tick, because the
        #: two are the same mechanism pointed in opposite directions: one asks
        #: whether to stop, this asks whether anything has been said. B120
        #: shipped the outward half — the run streams what it is doing — and
        #: named what was left: "a run that stops to ask a question still
        #: cannot be answered ... this is a window rather than a
        #: conversation." This is the inward half.
        #:
        #: `None` means nobody can answer, and then the child's stdin stays
        #: exactly what it was — `DEVNULL`, or the temp file holding a prompt
        #: too long for argv. That default matters: B125 is the scar from
        #: handing a CLI a *pipe* on stdin it did not expect, which on Windows
        #: crosses a `cmd.exe` and produced "no stdin data received in 3s". A
        #: pipe is opened only when someone is actually there to write to it.
        self.replies: Callable[[], list[str]] | None = None
        #: How often to look up from a silent stream and ask whether the reader
        #: has stopped this. Half a second: the reader's own measure is "did
        #: pressing stop stop it", and anything under a second reads as yes,
        #: while a tick this size costs one queue timeout per half-second of a
        #: run that is otherwise waiting on a network.
        self._cancel_tick = 0.5
        #: True while a run is talking to a child that reads *messages*, so a
        #: reply has to be framed rather than typed. Set per attempt, because
        #: the same researcher may fall back to the one-shot vector mid-run.
        self._conversing = False
        #: Whether the last `_stream` ever produced a line. Only conversational
        #: runs consult it: a child reading its prompt from a pipe that never
        #: arrived is silent rather than wrong, and silence is the only symptom
        #: it has.
        self._spoke = False
        #: The run's raw output, bounded. The reply is parsed out of this, and
        #: it is what a failure quotes its tail of.
        self.transcript = ""
        #: The lines this run narrated, in order. Kept so a caller that was not
        #: watching live can still ask what happened.
        self.actions: list[str] = []
        #: Reply text that has arrived but is not yet a sentence. See `_say`.
        self._said_partial = ""
        #: Why nothing came back, when nothing came back. `tasks.py` cannot
        #: read this yet; `_research`'s log gets it through the exception on
        #: the paths that are genuinely broken, and through an empty gather on
        #: the paths that merely found nothing.
        self.note = ""

    # ── gather ───────────────────────────────────────────────────────────────

    def gather(self, task: ResearchTask) -> list[Document]:
        # The scale reaches the agent as a sentence and the CLI as a flag,
        # and it has to be both. Truncating the reply afterwards — which is
        # all `raw[: max_documents * 8]` below ever did — saves the reader
        # nothing: by then the agent has already run thirty searches on their
        # subscription and only the bookkeeping is smaller. A budget is worth
        # something only if it is stated before the spending.
        self.max_documents = max(0, int(task.max_documents or 0))
        # Carried even though this plane bills a subscription rather than a
        # card: `vibe` is the one CLI here that will stop *itself* on a
        # dollar figure, and a ceiling the reader set should reach every CLI
        # that has somewhere to put it. Where there is nowhere, `scale_args`
        # drops it.
        self.budget_usd = max(0.0, float(task.budget_usd or 0.0))
        prompt = self.brief(task) + "\n" + self._contract()
        if self.harness.id in {"antigravity-cli", "mistral-vibe", "codex"}:
            from app.providers import exa_mcp, fetch
            from app.providers.local_agent import LocalAsker
            def complete(brief):
                return self._run("Answer ONLY from supplied pages. Do not call tools or run commands.\n" + brief)
            # An explicit cap keeps the CLI prompt below Windows' argv limit.
            setattr(complete, "prompt_chars_allowed", lambda: 22000)
            agent = LocalAsker(lambda _: "[]", complete, exa_mcp.search_with_fallback(), fetch.reader(),
                               model=self.requested_model or self.harness.id, search_provider="exa-mcp",
                               given_queries=list(task.queries)[:3] or [f"{task.subject_label} failures owner reports"], parallel_search=True)
            agent.max_pages = max(1, task.max_documents or 3)
            agent.on_action, agent.check_cancelled = self.on_action, self.check_cancelled
            reply = agent.ask(prompt)
            self.sources, self.telemetry = agent.sources, agent.telemetry
            self.search_provider = "exa-mcp"
        else:
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

    def _contract(self) -> str:
        """What is appended to the brief: how much to read, and how to report.

        A method so a plane that reports the same way but is *billed*
        differently can add its own ceiling: the Mistral API agent
        (`app/providers/apiagent.py`) pays per search, and a budget stated in
        pages says nothing about dollars.
        """
        return (budget_clause(self.max_documents) + CONTRACT
                + self.harness.contract_note)

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """What `gather` already parsed, per document. No second model call."""
        return list(self._by_url.get(document.url, ()))

    def ask_quick(self, product: str, *, principle: str = "", page=None, packs: str = "", attributes: str = "") -> str:
        if self.harness.id == "claude-code":
            from app import quicklook
            return self.ask(quicklook.brief(product, principle, page, packs, attributes)
                            + getattr(self, "source_instructions", ""))
        from app.providers import exa_mcp, fetch
        from app.providers.local_agent import LocalAsker
        # The host gathers evidence, then the CLI answers in a fresh, neutral
        # session. It never needs a shell command to research a product.
        calls = [0]
        def complete(prompt):
            calls[0] += 1
            return self._run("Use ONLY the supplied evidence. Do not call tools, run commands, or search. "
                             "Return the requested JSON object directly.\n" + prompt)
        agent = LocalAsker(lambda _: "[]", complete, exa_mcp.search_with_fallback(), fetch.reader(),
                           model=self.requested_model or self.harness.id, search_provider="exa-mcp",
                           given_queries=[f"{product} problems owner reports", f"{product} failures review"],
                           parallel_search=True)
        agent.max_pages = max(1, self.max_documents or 3)
        agent.on_action = self.on_action
        agent.check_cancelled = self.check_cancelled
        agent.source_instructions = getattr(self, "source_instructions", "")
        try:
            return agent.ask_quick(product, principle=principle, page=page, packs=packs, attributes=attributes)
        finally:
            self.sources = agent.sources
            self.telemetry = agent.telemetry
            self.telemetry["model_calls"] = calls[0]
            self.search_provider = "exa-mcp"

    def ask(self, prompt: str) -> str:
        """One prompt, one reply, for a job that is not research.

        Public because `tasks.pack_author` is a second caller with the same
        need and no interest in findings: it hands the agent a brief about a
        category and reads back a proposed pack. The plane's value is the
        *sandboxed spawn* — the allowlist, the neutral working directory, the
        one MCP server that only reads a page — and that is worth reusing rather than
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
        prompt = with_refused_page(prompt)
        with self._workspace():
            # Said only once the reader is really attached to this run: a note
            # about a tool that is not there would send the agent looking.
            if self._reader_config:
                prompt = with_page_reader(prompt, reader_tools(self.harness))
            return self._invoke(prompt, on_line)

    def _place_reader(self, folder: Path) -> None:
        """Write this run's page-reader config into its own folder (B155).

        Beside `opencode.json` and the sandbox `HOME`s below, for the same
        reason: a per-run grant lives in the run's folder and goes with it, and
        nothing of the reader's own configuration is written. Nothing is
        written for a CLI that cannot take it.
        """
        self._reader_config = ""
        if not reader_attachable(self.harness):
            return
        path = folder / READER_CONFIG_FILE
        path.write_text(json.dumps(reader_config()), encoding="utf-8")
        self._reader_config = str(path)

    @contextmanager
    def _workspace(self):
        if not self.harness.sandbox_home:
            # An empty directory to start in, even with the reader's own HOME
            # (B151). The old default was `~`, and on the reader's machine `~`
            # is a git repository: opencode snapshots its working tree before
            # its first model call, so every run spent its budget hashing a
            # home folder and printed nothing. A research run reads the web,
            # never the disk it happens to start on.
            with tempfile.TemporaryDirectory(prefix="kriko-research-") as directory:
                self._run_cwd = directory
                # The folder said twice, because a CLI may believe either.
                # opencode takes its project from `PWD` when one is set, and
                # a Kriko started from a shell hands down that shell's `PWD`:
                # the run then read the shell's folder (its `AGENTS.md`, its
                # `opencode.json`) and not the one it was started in (B154).
                self._run_env = {"PWD": directory}
                if self.harness.id == "opencode":
                    # **Why opencode "could not open any website" (B154).**
                    # opencode 2.x asks, once, which provider its `websearch`
                    # tool should use, and keeps the answer in its own
                    # database. `opencode run` has nobody to ask, so every
                    # search came back "Web search cancelled" while the agent
                    # file allowed it. A project `opencode.json` in the folder
                    # the run starts in answers the question for this run
                    # only — the reader's config and database stay as found,
                    # and the file goes with the folder. `exa`, because it
                    # answers without a key of the reader's; `random` can
                    # land on one that does not (Firecrawl) and return nothing.
                    (Path(directory) / "opencode.json").write_text(json.dumps({
                        "websearch": {"provider": "exa"},
                    }), encoding="utf-8")
                self._place_reader(Path(directory))
                try:
                    yield
                finally:
                    self._run_env = {}
                    self._run_cwd = None
                    self._reader_config = ""
            return
        with tempfile.TemporaryDirectory(prefix="kriko-research-") as directory:
            root = Path(directory)
            home = root / "home"
            work = root / "work"
            home.mkdir()
            work.mkdir()
            self._run_cwd = str(work)
            self._run_env = {"HOME": str(home), "USERPROFILE": str(home), "PWD": str(work)}
            if self.harness.protocol == "agy":
                # **The run's own permission policy, and nobody else's.**
                #
                # `agy` headless is `permission_mode: request-review`:
                # `search_web` runs unasked and `read_url_content` does not,
                # and print mode cannot answer a prompt — so it soft-denies,
                # and the run ends having searched six times, read nothing,
                # and returned an empty string after spending the reader's
                # quota. That was every Antigravity run there has ever been.
                #
                # The grant belongs in the CLI's own settings file, whose
                # path (`~/.gemini/antigravity-cli/settings.json`) and rule
                # grammar (`read_url(*)`, one of `command|read_file|
                # write_file|read_url|mcp|execute_url|unsandboxed`) were read
                # off the binary and then verified by running it. Writing it
                # under a `HOME` that vanishes with the run is the difference
                # between a plane that works and a plane that leaves a
                # standing permission on the reader's machine: Kriko grants
                # exactly what this run needs, for exactly as long as it runs.
                #
                # The login survives because `agy` keeps its token in the OS
                # keyring, not under `HOME`. Verified, not assumed — a
                # sandbox that silently logged the reader out would look
                # exactly like the bug it replaced.
                config = home / ".gemini" / "antigravity-cli"
                config.mkdir(parents=True)
                (config / "settings.json").write_text(json.dumps({
                    "permissions": {"allow": ["read_url(*)"]},
                }), encoding="utf-8")
            elif self.harness.protocol == "vibe":
                # Only the things that are nobody's business on a research
                # run: update checks, telemetry, the reader's MCP servers and
                # skills. The *tool* sandbox is `--enabled-tools`, which the
                # CLI documents as disabling everything it does not name in
                # programmatic mode — so there is no agent profile to write
                # and no schema of Mistral's for Kriko to keep in step with.
                config = home / ".vibe"
                config.mkdir(parents=True)
                try:
                    own = tomllib.loads((Path.home() / ".vibe" / "config.toml").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    own = {}
                chosen = self.requested_model or str(own.get("active_model") or "")
                if chosen:
                    self.model = chosen
                rows = own.get("models") or []
                text = 'enable_update_checks = false\nenable_telemetry = false\nmcp_servers = []\ndisabled_skills = ["*"]\n'
                if chosen:
                    text += "active_model = " + json.dumps(chosen) + "\n"
                if self.requested_effort and not any(isinstance(r, dict) and r.get("alias") == chosen for r in rows) and chosen:
                    rows = [*rows, {"alias": chosen}]
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    text += "\n[[models]]\n"
                    for key in ("name", "provider", "alias", "thinking"):
                        value = row.get(key)
                        if key == "thinking" and (row.get("alias") == chosen or row.get("name") == chosen) and self.requested_effort:
                            value = self.requested_effort
                        if isinstance(value, str):
                            text += key + " = " + json.dumps(value) + "\n"
                    if "thinking" not in row and self.requested_effort and row.get("alias") == chosen:
                        text += "thinking = " + json.dumps(self.requested_effort) + "\n"
                text += "\n[session_logging]\ngenerate_titles = false\nsave_dir = " + json.dumps(str(config / "sessions")) + "\n"
                (config / "config.toml").write_text(text, encoding="utf-8")
                self._run_env["VIBE_HOME"] = str(config)
                # The CLI reads its key from the environment, and the
                # environment this run inherits is the reader's own. Carried
                # across explicitly because `_stream` merges `_run_env` last:
                # an empty value here would blank a key that was working.
                for name in ("MISTRAL_API_KEY", "VIBE_API_KEY"):
                    if os.environ.get(name):
                        self._run_env[name] = os.environ[name]
            else:
                config = home / ".gemini"
                config.mkdir()
                (config / "settings.json").write_text(json.dumps({
                    "tools": {"core": ["google_web_search", "web_fetch"],
                              "allowed": ["google_web_search", "web_fetch"]},
                    "mcpServers": {},
                    "hooksConfig": {"enabled": False},
                    "skills": {"enabled": False},
                    "context": {"fileName": [], "includeDirectoryTree": False},
                    "general": {"enableAutoUpdate": False},
                    "security": {"auth": {"selectedType": "gemini-api-key"}},
                }), encoding="utf-8")
                self._run_env["GEMINI_CLI_HOME"] = str(home)
            self._place_reader(work)
            try:
                yield
            finally:
                if self.harness.protocol == "vibe":
                    # These files belong to this invocation's temporary home;
                    # never count another chat or read the user's session log.
                    for metadata in (config / "sessions").rglob("meta.json"):  # any-order: each file is counted once, the sum does not depend on order
                        try:
                            stats = json.loads(metadata.read_text(encoding="utf-8")).get("stats", {})
                            count = int(stats.get("session_prompt_tokens", 0)) + int(stats.get("session_completion_tokens", 0))
                            # Current Vibe stores cumulative usage in versioned
                            # projections. Count the latest measurement once,
                            # never sum historical snapshots of the same chat.
                            for projection in (metadata.parent / "generations").glob("*/projection-state.json"):  # any-order: the largest measurement wins
                                snapshot = json.loads(projection.read_text(encoding="utf-8")).get("snapshot", {})
                                usage = snapshot.get("session", {}).get("tokenUsage") or {}
                                count = max(count, int(usage.get("inputTokens", 0)) + int(usage.get("outputTokens", 0)))
                            if count > 0:
                                self.tokens_used = (self.tokens_used or 0) + count
                        except (OSError, ValueError, TypeError):
                            pass
                self._run_env = {}
                self._run_cwd = None
                self._reader_config = ""

    def _invoke(self, prompt: str, on_line: Callable[[str], None] | None) -> str:
        if self.harness.id == "opencode":
            _ensure_opencode_agent()
        command = command_for(
            self.harness,
            model=self.requested_model,
            effort=self.requested_effort,
            max_documents=self.max_documents,
            budget_usd=self.budget_usd,
            reader_config=self._reader_config,
        )
        if self.harness.protocol in ("vibe", "gemini"):
            command.extend(["--prompt", ""])
        # A model named for a CLI that has no flag for one. `_workspace` has
        # already built `_run_env` by the time this runs, and `_stream` merges
        # it over the inherited environment — so this is the same per-run
        # switch `--model` is, expressed the only way this CLI offers.
        if self.requested_model and not self.harness.model_flag and self.harness.model_env:
            self._run_env[self.harness.model_env] = self.requested_model
        say = on_line if on_line is not None else self.on_action
        if say is not None and self.effort_settled:
            say(self.effort_settled)

        self._conversing = False
        if self._can_converse():
            # The whole point of this branch: the child reads messages for as
            # long as it runs, so the brief is the first one and the reader's
            # answer is the next. Every other path here hands over a prompt
            # and then talks to a process that cannot hear.
            self._conversing = True
            code, stdout, stderr = self._stream(
                [*command, self.harness.reply_flag, self.harness.reply_value],
                subprocess.DEVNULL,
                say,
                opening=self._frame(prompt),
            )
            if not self._spoke:
                # It never said a word — the pipe, not the model. Fall through
                # to the ordinary vector rather than failing the job: a run the
                # reader cannot answer is worth far more than no run at all,
                # and this is the one case where we know which of the two we
                # are looking at.
                self._conversing = False
                self._echo(
                    f"{self.harness.label} did not start in conversational "
                    "mode; running it the ordinary way, so this run cannot "
                    "be answered"
                )
            else:
                return self._finish(code, stdout, stderr)

        if self.harness.prompt_flag:
            # A CLI whose prompt is a flag's value, with no `--` convention
            # and no stdin prompt to fall back on (verified: piped input is
            # ignored, and an empty `-p` eats the next flag as its value).
            if not prompt.strip():
                raise RuntimeError(f"{self.harness.label} needs a non-empty prompt")
            if len(prompt) > MAX_PROMPT_ARGUMENT:
                raise RuntimeError(
                    f"{self.harness.label} cannot take this prompt "
                    f"({len(prompt)} characters); shorten the brief and retry"
                )
            code, stdout, stderr = self._stream(
                [*command, self.harness.prompt_flag, prompt],
                subprocess.DEVNULL,
                say,
            )
        elif self.harness.prompt_argument and len(prompt) <= MAX_PROMPT_ARGUMENT:
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

        return self._finish(code, stdout, stderr)

    def _finish(self, code: int, stdout: str, stderr: str) -> str:
        """What a completed spawn means, whichever vector produced it.

        Lifted out of `_invoke` when the conversational vector gave it a
        second exit to read. One reading of an exit code, in one place — the
        alternative was two, and the second one would have been the one that
        forgot to meter.
        """
        if code != 0:
            envelope = _envelope(stdout) if self.harness.structured else {}
            # Metered before raising. A run that failed on its fourth search
            # still spent the reader's subscription on three, and a plane that
            # only counts what succeeded is a plane whose cost column lies.
            self._meter(envelope)
            reason = _why(envelope, stdout, stderr)
            hint = _hint(reason, self.harness)
            raise RuntimeError(
                f"{self.harness.label} exited {code}: {reason}"
                + (f" -- {hint}" if hint else "")
            )
        if not self.harness.structured:
            return stdout
        return self._unwrap(stdout)

    def _can_converse(self) -> bool:
        """Whether this run can be *answered*, rather than merely noted.

        Three things have to hold, and each is a way this has already gone
        wrong. Somebody must be able to answer (`replies`), or the pipe buys
        nothing and costs the B125 risk for free. There must be a framing we
        know how to write, which is `protocol`'s business and not the
        executable's name. And the flag must be declared by the CLI *on this
        machine*: the reader's `claude` is not this one, and a vector an older
        build has never heard of is a run that dies on argument parsing rather
        than a run that merely cannot be answered.
        """
        if self.replies is None or not self.harness.reply_flag:
            return False
        if self.harness.protocol != "claude":
            return False
        try:
            return self.harness.reply_flag in declared(locate(self.harness))
        except Exception:  # noqa: BLE001 - a plain run, not a lost one
            return False

    def _frame(self, text: str) -> str:
        """One message, in the shape the CLI reads them in.

        `stream-json` going in is the same envelope it uses coming out: one
        JSON object per line, `type` naming what it is. This is the user's
        turn — which is what the opening brief and every later reply both are.
        The CLI does not distinguish them, and neither does this.
        """
        return json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                },
            },
            ensure_ascii=False,
        )

    def _close_stdin(self, proc) -> None:
        """Tell the child nothing more is coming. Never fatal."""
        if proc.stdin is None:
            return
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _deliver(self, proc) -> bool:
        """Hand the child whatever the reader has said, if anything.

        True when at least one line reached the pipe.

        Called on the silent tick rather than on a line, because a run that
        has stopped to ask something is precisely a run producing no output —
        waiting for a line before checking for an answer would mean the answer
        only ever arrived after the thing it was answering had moved on.

        Never fatal. A child that closed its stdin, or died between the tick
        and the write, is not a reason to lose a run of real research; the
        reader sees the reply was not taken up because the run carries on
        saying what it was saying.
        """
        # A closed stdin is a finished turn (see `_stream`). Asking for the
        # replies anyway would mark them taken and then drop them on the
        # floor — the one outcome worse than not delivering them.
        if self.replies is None:
            return False
        if not self._conversing:
            # Nobody on the other end can hear it. Taken anyway, and said so
            # in the transcript, so the reader's line is neither left waiting
            # for a pipe that will never exist nor reported as heard.
            try:
                lines = self.replies()
            except Exception:  # noqa: BLE001
                return False
            for line in lines:
                self._echo(
                    f"you: {_short(line)} (not heard: {self.harness.label} "
                    "cannot take a reply mid-run)"
                )
            return False
        if proc.stdin is None or proc.stdin.closed:
            return False
        # Not before the brief is through: two writers on one pipe interleave,
        # and a reply spliced into the middle of the opening is two broken
        # messages. Left unread, so it is delivered on the next tick instead.
        opening_sent = getattr(self, "_opening_sent", None)
        if opening_sent is not None and not opening_sent.is_set():
            return False
        try:
            lines = self.replies()
        except Exception:  # noqa: BLE001 - narration must never end a run
            return False
        delivered = False
        for line in lines:
            try:
                body = line.rstrip("\n")
                proc.stdin.write(
                    (self._frame(body) if self._conversing else body) + "\n"
                )
                proc.stdin.flush()
            except (OSError, ValueError):
                return delivered
            delivered = True
            self._echo(f"you: {_short(line)}")
        return delivered

    def _echo(self, line: str) -> None:
        """Put the reader's own line in the transcript they are watching.

        Not `_narrate`, which turns a *CLI event* into a sentence — this line
        did not come from the CLI. But it belongs in the same list, because an
        answer that is not in the transcript leaves the hole B120 named one
        turn later: the log would show the question and the run carrying on,
        with no record of what changed its mind.
        """
        self.actions.append(line)
        if self.on_action is not None:
            try:
                self.on_action(line)
            except Exception:  # noqa: BLE001 - a worse log, not a lost run
                pass

    def _stream(self, command, stdin_read, say, opening: str = "") -> tuple[int, str, str]:
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
        self._spoke = False
        command = unshim(command)
        # See `_new_job_object`: on Windows this is what lets a cancel reach
        # a descendant `taskkill /T` cannot, because its parent already
        # exited. `None` on POSIX, where `start_new_session`/`killpg` already
        # cover the tree — every caller of `_kill_tree` below treats it the
        # same way regardless of which platform gave it.
        job = self._new_job_object()
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed executable, no shell
                command,
                # A pipe only for a conversation. A one-shot CLI cannot hear a
                # line mid-run, and an open pipe to one is all risk: a CLI that
                # reads a non-tty stdin to EOF (`claude -p` does, for three
                # seconds; plenty of scripts do forever) waits on a pipe we
                # have no reason to close. See `self.replies` for why DEVNULL
                # is load-bearing rather than merely conservative.
                stdin=subprocess.PIPE if opening else stdin_read,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**child_env(extra_dirs=(str(Path(command[0]).parent),) if os.path.isabs(command[0]) else ()), **CHILD_ENCODING_ENV, **self.harness.env, **self._run_env},
                cwd=self._run_cwd or os.path.expanduser("~"),
                shell=self._needs_shell(command),
                startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
        self._assign_job(job, proc)

        # The opening message. A conversational child has no prompt until this
        # lands — it is the run, not a preamble to it.
        #
        # **Written on its own thread (B147).** It used to be written here,
        # inline, before stdout had a reader. A brief larger than the pipe
        # buffer (the pack author's is ~10 KB; Windows gives a pipe 4 KB)
        # blocks the write until the child reads — and `claude` prints its
        # `init` event, kilobytes of tool and skill names, *before* reading.
        # Nobody was reading that, so the child blocked on stdout, the write
        # blocked on stdin, and the run sat silent with no heartbeat, no
        # cancel and not even the timeout timer started, until the reader
        # closed the app. Ten minutes of one reader's evening, reproduced by
        # `test_a_brief_larger_than_the_pipe_does_not_deadlock_a_chatty_child`.
        self._opening_sent = None
        opening_failed: list[BaseException] = []
        if opening:
            sent = threading.Event()
            self._opening_sent = sent

            def _send_opening() -> None:
                try:
                    assert proc.stdin is not None
                    proc.stdin.write(opening.rstrip("\n") + "\n")
                    proc.stdin.flush()
                except (OSError, ValueError, AssertionError) as exc:
                    opening_failed.append(exc)
                finally:
                    sent.set()

            threading.Thread(target=_send_opening, daemon=True).start()

        began = time.monotonic()
        said: list[str] = []
        # The same list, not a copy: `_echo` appends the reader's replies to
        # `self.actions` mid-run, and the `self.actions = said` at the end
        # would otherwise replace the transcript with one that never heard them.
        self.actions = said
        errors: list[str] = []
        drain = threading.Thread(
            target=self._drain, args=(proc.stderr, errors), daemon=True
        )
        drain.start()

        expired = threading.Event()

        def _give_up() -> None:
            expired.set()
            self._kill_tree(proc, job)

        timer = threading.Timer(self.timeout, _give_up)
        timer.start()
        narrated = 0
        #: When the child last printed anything, and when the log last heard
        #: from this run at all (a line or a heartbeat) — see HEARTBEAT_SECONDS.
        last_heard = last_line = began
        #: When a turn ended on a question, and how long its answer may take.
        waiting_since: float | None = None
        waiting_for = 0.0
        assert proc.stdout is not None
        try:
            for line in _lines(proc.stdout, self._cancel_tick):
                if line is None:
                    # The stream said nothing for a tick. That is not idleness
                    # — it is the *normal* shape of a long model call, and it
                    # used to be the shape of an uncancellable one: the loop
                    # sat inside `for line in proc.stdout` and a reader who
                    # pressed stop waited for whatever byte came next, which on
                    # a deep run is minutes of spending they had already said
                    # no to.
                    if self.check_cancelled is not None:
                        self.check_cancelled()
                    now = time.monotonic()
                    if say is not None and now - last_heard >= HEARTBEAT_SECONDS:
                        last_heard = now
                        try:
                            say(
                                f"still working — {_minutes(now - began)} in; "
                                f"{self.harness.label} is thinking and has not "
                                f"printed anything new for "
                                f"{_minutes(now - last_line)}"
                            )
                        except Exception:  # noqa: BLE001 — see the docstring
                            say = None
                    # A conversational child that has not said one word is a
                    # pipe that did not arrive, not a model thinking hard: the
                    # `init` event comes before the first API call. Give up
                    # early so the caller can run it the ordinary way, rather
                    # than holding the job worker for the whole timeout.
                    if (opening and not self._spoke
                            and time.monotonic() - began > CONVERSATION_START_SECONDS):
                        self._kill_tree(proc, job)
                        break
                    if self._deliver(proc):
                        # An answer to the question it ended on: that is the
                        # next turn starting, so the wait below is over.
                        waiting_since = None
                    elif (waiting_since is not None
                            and time.monotonic() - waiting_since > waiting_for):
                        self._echo("no answer came; the run ends here")
                        self._close_stdin(proc)
                        waiting_since = None
                    continue
                self._spoke = True
                last_heard = last_line = time.monotonic()
                self._keep(line)
                # A child reading messages does not exit when its turn ends —
                # it waits for the next one, and stdout stays open while it
                # waits. The `result` event is the end of the turn, so it is
                # the moment to say nothing more is coming; without this the
                # loop above reads a pipe that never closes.
                #
                # Unless the turn ended on a question. An agent in `-p` does
                # not stop mid-turn to ask — it finishes the turn *with* the
                # question — so closing here would be the one-shot run again,
                # with the reader's answer arriving at a pipe nobody reads. It
                # gets a bounded wait instead, never past the run's own
                # timeout: a timeout discards the run, and a run that asked
                # and heard nothing still has everything it found.
                if self._conversing and proc.stdin is not None and _is_result(line):
                    left = self.timeout - (time.monotonic() - began) - 10.0
                    waiting_for = min(ANSWER_WAIT_SECONDS, left)
                    if self._deliver(proc):
                        # A reply that was waiting is the next turn; whether
                        # the pipe closes is decided at *that* turn's end.
                        pass
                    elif _asks(line) and waiting_for > 0:
                        waiting_since = time.monotonic()
                        self._echo("waiting for your answer")
                    else:
                        self._close_stdin(proc)
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
            # stdout has ended, so nothing more can be asked and nothing more
            # can be answered. Closing tells a child that is politely waiting
            # for one more line that there will not be one — without it a run
            # whose stdin we opened could sit past its own output forever.
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass
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
                self._kill_tree(proc, job)
            if sys.platform == "win32" and job is not None:
                try:
                    import ctypes

                    ctypes.windll.kernel32.CloseHandle(job)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
            drain.join(timeout=5.0)
            # A pipe a surviving grandchild still holds open blocks `close()`
            # forever on Windows (see the module docstring's job-object note)
            # — the job kill above should have left nothing holding one, but
            # "should have" is not a guarantee this worker thread may act on.
            # Closing on a daemon thread means a pipe that still won't let go
            # leaks a handle, never wedges the one worker every other job is
            # waiting behind.
            def _close_pipes() -> None:
                for pipe in (proc.stdout, proc.stderr):
                    if pipe is None:
                        continue
                    try:
                        pipe.close()
                    except Exception:  # noqa: BLE001
                        pass

            closer = threading.Thread(target=_close_pipes, daemon=True)
            closer.start()
            closer.join(timeout=5.0)

        self.actions = said
        if opening_failed and not self._spoke:
            # The child died before it read the brief. The reason is on its
            # stderr, not in the broken-pipe exception (knowledge-6), and the
            # caller retries the ordinary way on this error.
            tail = "".join(errors).strip()
            raise RuntimeError(
                f"{self.harness.label} would not take the brief on stdin"
                + (f": {tail}" if tail else "")
            ) from opening_failed[0]
        if expired.is_set():
            raise TimeoutError(
                f"{self.harness.label} did not finish within {int(self.timeout)}s"
            )
        return proc.returncode or 0, self.transcript, "".join(errors)

    @staticmethod
    def _new_job_object():
        """Windows only: a Job Object the child is placed into at spawn time.

        `taskkill /T` walks the *live* parent-pid chain, so it misses any
        descendant whose parent has already exited by the time the kill
        runs — and a conversing harness always has one: the shim that reads
        the reply off stdin outlives the CLI it was piping into. A process
        placed in a job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` stays a
        member of that job for its whole life regardless of what its own
        parent does, so `TerminateJobObject` reaches it — an orphan is still
        in the job even when it is no longer in anyone's process tree.

        Returns `None` on POSIX (where `killpg` already does this job) and
        whenever the Windows API call itself fails, so every caller treats
        "no job object" as "fall back to `taskkill`" rather than a fault.
        """
        if sys.platform != "win32":
            return None
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return None

            class _BASIC(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32),
                ]

            class _IO_COUNTERS(ctypes.Structure):
                _fields_ = [(name, ctypes.c_uint64) for name in (
                    "ReadOperationCount", "WriteOperationCount",
                    "OtherOperationCount", "ReadTransferCount",
                    "WriteTransferCount", "OtherTransferCount",
                )]

            class _EXTENDED(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", _BASIC),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
            JobObjectExtendedLimitInformation = 9
            info = _EXTENDED()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                job, JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info),
            )
            if not ok:
                kernel32.CloseHandle(job)
                return None
            return job
        except Exception:  # noqa: BLE001 — no job object is a fallback, not a fault
            return None

    @staticmethod
    def _assign_job(job, proc) -> None:
        """Put `proc` in `job`, best-effort, right after `Popen` returns.

        Has to happen before the child can spawn anything of its own — a
        grandchild started after this point inherits its parent's job
        membership automatically (Windows does not offer an opt-in; only an
        opt-out, `CREATE_BREAKAWAY_FROM_JOB`, which nothing here sets), which
        is the whole reason a job object catches what `taskkill /T` misses.
        """
        if job is None:
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = getattr(proc, "_handle", None)
            if handle is None:
                return
            kernel32.AssignProcessToJobObject(job, int(handle))
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _kill_tree(proc, job=None) -> None:
        """End the whole process, not just the one pid this object holds.

        `_needs_shell` means the pid here is sometimes `cmd.exe`, whose real
        child (the CLI, and whatever it forked for a fetch) `proc.kill()`
        never touches — a run declared timed out would keep spending the
        reader's subscription in the background, invisibly, past the
        deadline this exists to enforce. `start_new_session=True` on spawn is
        what makes a tree kill possible on POSIX (`killpg` reaches the whole
        session).

        On Windows, `job` (from `_new_job_object`/`_assign_job`) is tried
        first: `TerminateJobObject` kills every process ever assigned to it,
        orphaned or not, which is what a conversing CLI's surviving
        descendant needs (see `_new_job_object`'s docstring). `taskkill /T`
        still runs afterwards as a belt for a process this job never held —
        one spawned before assignment raced it, say. Every step is
        best-effort — a process that is already gone by the time this runs
        is the good outcome, not a failure to report.
        """
        if sys.platform == "win32" and job is not None:
            try:
                import ctypes

                ctypes.windll.kernel32.TerminateJobObject(job, 1)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10,
                    startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
    def _drain(pipe, into: list, keep: int = 400) -> None:
        try:
            for line in pipe:
                into.append(line)
                if len(into) > keep:
                    del into[: len(into) - keep]
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

        **The reply arrives in pieces, and a log line is not a piece.**
        Antigravity streams its answer as `text_delta` fragments a few
        characters long — "em OR issue", "\\"findings\\": [ { \\"titl", "e\\":
        " — so narrating each one turned a run's log into forty lines of
        shredded JSON. `_say` joins them back into sentences; everything
        else passes straight through.
        """
        if not self.harness.structured:
            return _short(line, 200)
        try:
            event = json.loads(line)
        except ValueError:
            return ""
        if not isinstance(event, dict):
            return ""
        return self._say(event, narrate(event))

    #: The longest run of streamed reply text held back waiting for a
    #: sentence to end. Past it the buffer is logged as it stands: an agent
    #: printing a long JSON fence has no sentence endings in it at all, and
    #: a log that says nothing for two minutes is the silence B121 fixed.
    SAY_BUFFER = 240

    def _say(self, event: dict, said: str) -> str:
        """`said`, once it is a whole thought rather than a fragment.

        Only the model's own prose is buffered. A tool call, a failure and
        the result line are each already one complete statement, and holding
        them back would delay the very lines a reader is watching for.
        """
        step = event.get("step_update")
        # Narrowed in the `if` itself rather than through a boolean: a name
        # holding the result of `isinstance` tells a reader what is true but
        # tells a type-checker nothing, and the two `step.get` calls below are
        # only safe because of it.
        if not (isinstance(step, dict)
                and step.get("step_type") == "agent_response"):
            # Anything else flushes what the reply had accumulated first, so
            # the log keeps the order things actually happened in.
            held, self._said_partial = self._said_partial, ""
            held = _short(held, 200)
            return f"{held} {said}".strip() if held and said else (said or held)
        self._said_partial += str(step.get("text_delta") or "")
        done = step.get("state") == "DONE"
        ended = self._said_partial.rstrip().endswith((".", "!", "?", "}", "```"))
        if not done and not ended and len(self._said_partial) < self.SAY_BUFFER:
            return ""
        held, self._said_partial = self._said_partial, ""
        return _short(held, 200)

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

    def _unwrap_vibe(self, stdout: str) -> str:
        """Mistral Vibe's reply, out of its stream of history entries.

        `--output streaming` prints one `PublicHistoryEntry` per line and
        **no result object at the end** — there is nothing shaped like
        `{"result": …}` for `_envelope` to find, so without this the whole
        NDJSON stream would be handed to `_payload` as prose and the fence
        inside it would already be JSON-escaped past recognition.

        Every completed assistant message, joined in order: the fence is in
        the last one, and a model that split its reply across two messages
        should not lose it to a rule that only read the final line. Entries
        are camelCase on the wire (`alias_generator=to_camel` on the CLI's
        own `ProtocolModel`), which is why `generationStatus` is spelled the
        way it is.

        Nothing here meters. The stream carries no usage, so this plane's
        cost columns stay NULL — "cannot count" rather than a guess.
        """
        said: list[str] = []
        for line in (stdout or "").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "message":
                continue
            if entry.get("role") != "assistant":
                continue
            status = str(entry.get("generationStatus") or "").lower()
            if status and status != "completed":
                continue
            for block in entry.get("content") or ():
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text") or "")
                    if text.strip():
                        said.append(text)
        # The raw stream when nothing parsed, for the same reason `_unwrap`
        # hands back prose it could not read: the fence may still be in it,
        # and losing a completed run to a shape change would be absurd.
        return "\n".join(said) if said else stdout

    def _unwrap_copilot(self, stdout: str) -> str:
        """Copilot's reply, out of its JSONL event stream.

        Its terminal `{"type": "result"}` line carries an exit code, a session
        id and a usage block — and **no reply text at all**. The answer is in
        the `assistant.message` events before it, one per whole message, so
        this joins them in order for the reason `_unwrap_vibe` does: a model
        that split its findings fence across two messages must not lose it to
        a rule that read only the last one.

        A failure reported at exit 0 is refused here, the same as everywhere
        else in this file. `session.error` is how a model refusal or a tool
        error arrives, and the CLI has been seen to print one, end the turn
        and still exit 0 about it.

        Nothing here meters: the usage block counts premium requests and
        milliseconds, not tokens, so this plane's cost columns stay NULL
        rather than being filled with a number that means something else.
        """
        said: list[str] = []
        failure = ""
        for line in (stdout or "").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            data = event.get("data")
            data = data if isinstance(data, dict) else {}
            if event.get("type") == "assistant.message":
                text = str(data.get("content") or "")
                if text.strip():
                    said.append(text)
            elif event.get("type") == "session.error":
                failure = failure or str(data.get("message") or "").strip()
            elif event.get("type") == "model.call_failure":
                failure = failure or str(data.get("errorMessage") or "").strip()
        if not said and failure:
            hint = _hint(failure, self.harness)
            raise RuntimeError(
                f"{self.harness.label} reported an error: {failure[:500]}"
                + (f" -- {hint}" if hint else "")
            )
        return "\n".join(said) if said else stdout

    def _unwrap(self, stdout: str) -> str:
        """The assistant's text out of the CLI's JSON envelope, plus the usage.

        The shape-reading is `_envelope`'s, which the failure path shares:
        one object, an array of stream messages, or one object per line. A
        reply that is not JSON at all is handed back as prose rather than
        discarded — the findings fence may still be in it.
        """
        if self.harness.protocol == "codex":
            answer = ""
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "turn.failed":
                    raise RuntimeError(str(event.get("error") or "Codex turn failed"))
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    answer = item.get("text") or answer
                if event.get("type") == "turn.completed":
                    usage = event.get("usage") or {}
                    self.tokens_used = (self.tokens_used or 0) + _int(usage.get("input_tokens")) + _int(usage.get("output_tokens"))
            return answer
        if self.harness.protocol == "vibe":
            return self._unwrap_vibe(stdout)
        if self.harness.protocol == "copilot":
            return self._unwrap_copilot(stdout)
        envelope = _envelope(stdout)
        if not envelope:
            return stdout

        self._meter(envelope)
        status = envelope.get("status")
        if envelope.get("is_error") or (
            status is not None and status != "SUCCESS"
        ):
            # Same treatment as a non-zero exit, because it is the same
            # failure: the CLI reports a refusal, a limit or a billing
            # stop in the envelope and exits 0 about it.
            reason = _why(envelope, stdout, "")[:500]
            hint = _hint(reason, self.harness)
            raise RuntimeError(
                f"{self.harness.label} reported an error: {reason}"
                + (f" -- {hint}" if hint else "")
            )
        result = envelope.get("result")
        if not isinstance(result, str):
            result = envelope.get("response")
        if isinstance(result, str) and not result.strip():
            denied = envelope.get("denied_actions")
            if isinstance(denied, list) and denied:
                # Verified shape: exit 0, empty reply, and the tools the run
                # needed listed as denied. An empty gather downstream would
                # read as "researched, found nothing" — it was neither.
                reason = _why(envelope, stdout, "")[:500]
                hint = _hint(reason, self.harness)
                raise RuntimeError(
                    f"{self.harness.label} answered nothing: {reason}"
                    + (f" -- {hint}" if hint else "")
                )
        return result if isinstance(result, str) else stdout


def _site(url: str) -> str:
    """The host, for the log line. Not a parse — just the readable part."""
    without = url.split("://", 1)[-1]
    return without.split("/", 1)[0]
