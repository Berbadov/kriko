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
from dataclasses import dataclass, field

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
    #: Why this CLI cannot be used, if it cannot. Non-empty means `available()`
    #: will not offer it, while `/api/research-planes` still reports that it
    #: was found — "your opencode is installed and Kriko will not use it, and
    #: here is why" is an answer; silently ignoring it is not.
    unusable: str = ""


def _claude_args() -> tuple[str, ...]:
    return (
        "-p",
        "--output-format", "json",
        "--allowedTools", ",".join(SEARCH_TOOLS),
    )


#: In preference order. The first *usable* one found on PATH is the one used,
#: and `/api/research-planes` reports which.
KNOWN = (
    Harness("claude-code", "Claude Code", "claude", _claude_args()),
    # Found, reported, and not driven. `opencode run` has no flag that
    # restricts which tools the agent may use — `--help` offers `--agent`, and
    # naming an agent is trusting a profile rather than granting a set. The
    # allowlist is not a preference here; it is the reason this plane is
    # allowed to exist at all, and a research plane that can run `bash` on the
    # reader's machine is a remote-code path with extra steps. Ship one fewer
    # plane instead. Re-enable the moment the CLI grows a tool grant.
    Harness(
        "opencode",
        "opencode",
        "opencode",
        ("run",),
        structured=False,
        unusable=(
            "opencode's command line has no way to restrict which tools the "
            "agent may use, and Kriko will not start a research agent it "
            "cannot hold to search and fetch"
        ),
    ),
)


def available() -> list[Harness]:
    """Which harness CLIs this machine can actually start *and* sandbox."""
    return [h for h in KNOWN if not h.unusable and shutil.which(h.executable)]


def found_but_unusable() -> list[Harness]:
    """Installed, and deliberately not driven. For the screen to explain."""
    return [h for h in KNOWN if h.unusable and shutil.which(h.executable)]


def chosen(preferred: str = "") -> Harness | None:
    found = available()
    if preferred:
        return next((h for h in found if h.id == preferred), None)
    return found[0] if found else None


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
        command = [self.harness.executable, *self.harness.args]
        try:
            done = subprocess.run(  # noqa: S603 - fixed executable, no shell
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env={**os.environ, **self.harness.env},
                # A harness started in the repo would find its own project
                # config and its own tools. Home is neutral and is where a
                # reader's own subscription config lives.
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

        if done.returncode != 0:
            detail = (done.stderr or done.stdout or "").strip()[:2000]
            raise RuntimeError(
                f"{self.harness.label} exited {done.returncode}: "
                f"{detail or 'no output'}"
            )
        if not self.harness.structured:
            return done.stdout or ""
        return self._unwrap(done.stdout or "")

    def _unwrap(self, stdout: str) -> str:
        """The assistant's text out of the CLI's JSON envelope, plus the usage.

        Tolerant of a CLI that prints progress lines before its result: the
        last parseable object wins. A reply that is not JSON at all is handed
        back as prose rather than discarded — the findings fence may still be
        in it.
        """
        envelope = None
        for line in reversed((stdout or "").strip().splitlines()):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                envelope = parsed
                break
        if envelope is None:
            try:
                parsed = json.loads(stdout)
            except ValueError:
                return stdout
            envelope = parsed if isinstance(parsed, dict) else None
        if envelope is None:
            return stdout

        tokens = _tokens(envelope.get("usage") or {})
        if tokens:
            self.tokens_used = tokens
        cost = envelope.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            self.cost_usd = float(cost)
        if envelope.get("is_error"):
            raise RuntimeError(
                f"{self.harness.label} reported an error: "
                f"{str(envelope.get('result') or '')[:500]}"
            )
        result = envelope.get("result")
        return result if isinstance(result, str) else stdout


def _site(url: str) -> str:
    """The host, for the log line. Not a parse — just the readable part."""
    without = url.split("://", 1)[-1]
    return without.split("/", 1)[0]
