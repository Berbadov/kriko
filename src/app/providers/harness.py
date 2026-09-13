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
import subprocess
import tempfile
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
    return (
        "-p",
        "--output-format", "json",
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

_OPTION = re.compile(r"--[a-z][a-z0-9-]+")


def declared(executable: str) -> frozenset[str]:
    """Every long option this machine's copy of `executable` declares.

    Feature detection rather than a version check: the reader is on
    `claude_code_version 2.1.261` and this machine is not, versions are not
    ordered the way flag support is, and `--help` is the CLI's own answer.

    An empty set on any failure, which reads as "declares nothing extra" and
    costs the reader nothing but the hygiene flags — a missing CLI is already
    `NoHarness`, and a `--help` that hangs must not become a plane that hangs.
    """
    if executable in _DECLARED:
        return _DECLARED[executable]
    try:
        done = subprocess.run(  # noqa: S603 - fixed executable, no shell
            [executable, "--help"], capture_output=True, text=True, timeout=30
        )
        found = frozenset(_OPTION.findall((done.stdout or "") + (done.stderr or "")))
    except Exception:
        found = frozenset()
    _DECLARED[executable] = found
    return found


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
    return [executable, *one.args, *(f for f in one.preferred if f in supported)]


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
    for line in reversed(text.splitlines()):
        try:
            one = json.loads(line)
        except ValueError:
            continue
        if isinstance(one, dict):
            return one
    return {}


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
     "the CLI is not logged in. Run `claude` once in a terminal, log in, and "
     "press this again."),
    (("credit balance", "billing", "payment"),
     "the account behind the CLI cannot pay for this run."),
    (("error_max_turns",),
     "the agent ran out of turns before it reported. This is Kriko's to fix, "
     "not yours -- please send the log."),
    (("enoent", "not recognized", "cannot find the path"),
     "the CLI could not start. Reinstall Claude Code, or check that `claude` "
     "runs in a terminal."),
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

    def _run(self, prompt: str) -> str:
        """The prompt goes in on **stdin**, never as an argument.

        This is the defect that made B92 ship a plane that could not run at
        all. `claude --help` declares `--allowedTools <tools...>`: a *variadic*
        option, which swallows every following argument. So a vector ending
        `--allowedTools WebSearch,WebFetch <prompt>` handed the brief to the
        allowlist and left the CLI with no prompt, and the reader got

            Claude Code exited 1: Error: Input must be provided either
            through stdin or as a prompt argument when using --print

        after waiting out a run. Stdin is not a workaround for that one flag —
        it removes the whole class: no argument order can consume it, no
        quoting can mangle it, and a 4 KB brief cannot run into a command-line
        length limit (Windows caps a process's at 32,767 characters, and a
        brief plus a contract plus a pack's principle is on the same order).

        `test_the_harness_command_line_is_one_the_cli_accepts` runs the real
        CLI with an empty prompt and asserts its only complaint is the empty
        prompt, which is free and needs no API call. Every previous gate here
        asserted the *shape* of `args` and none asserted the CLI would take
        them — the same mistake as the twelve tray tests that passed on a
        `main.rs` which could not parse (B89).
        """
        if self.harness.id == "opencode":
            _ensure_opencode_agent()
        command = command_for(self.harness)
        fd, stdin_path = tempfile.mkstemp(prefix="kriko-harness-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stdin_write:
                stdin_write.write(prompt)
            with open(stdin_path, "r", encoding="utf-8") as stdin_read:
                try:
                    done = subprocess.run(  # noqa: S603 - fixed executable, no shell
                        command,
                        stdin=stdin_read,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout,
                        env={**os.environ, **self.harness.env},
                        cwd=os.path.expanduser("~"),
                    )
                except FileNotFoundError as exc:
                    raise NoHarness(
                        f"{self.harness.label} is not on PATH ({self.harness.executable})"
                    ) from exc
                except subprocess.TimeoutExpired as exc:
                    raise TimeoutError(
                        f"{self.harness.label} did not finish within "
                        f"{int(self.timeout)}s"
                    ) from exc
        finally:
            os.remove(stdin_path)

        if done.returncode != 0:
            envelope = _envelope(done.stdout or "") if self.harness.structured else {}
            # Metered before raising. A run that failed on its fourth search
            # still spent the reader's subscription on three, and a plane that
            # only counts what succeeded is a plane whose cost column lies.
            self._meter(envelope)
            reason = _why(envelope, done.stdout or "", done.stderr or "")
            hint = _hint(reason)
            raise RuntimeError(
                f"{self.harness.label} exited {done.returncode}: {reason}"
                + (f" -- {hint}" if hint else "")
            )
        if not self.harness.structured:
            return done.stdout or ""
        return self._unwrap(done.stdout or "")

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
