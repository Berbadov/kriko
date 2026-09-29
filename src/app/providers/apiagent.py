"""Research agents reached over an API instead of spawned as a CLI (B153).

The harness plane hands a coding-agent CLI a reading task. On 2026-09-29 the
reader reported how that goes: "Agent operations are slow and not working
properly". Measured the same day, every failure belonged to the CLI, not to
the run:

* fetches refused with 403;
* "you have no Kriko tools" read as "you have no tools", and no research done;
* OAuth and quota walls, and a Windows shim that mangles argv;
* about 104k tokens and 30 s spent per subject before a single page was read.

A process boundary this code does not own cannot be fixed from this side of
it. So this module reaches the same model family over HTTP instead: one
request carries the brief and a web-search tool, and it returns both the
answer and *what the search returned*.

The second half is what the CLI transcript never had. `HarnessResearcher`
trusts the `document_text` an agent pastes. This checks each quote against the
text the search tool produced for that url, and a quote that is not in it is
dropped and counted.

To `app/web/tasks.py` it is still the `harness` plane. It runs the same brief,
the same output contract and the same parser, so pack authoring, quick look
and research take it without a second code path. What differs is stamped on
the instance and read duck-typed, as everywhere else: `cost_basis`, `spent`,
`tokens_used`, and the `model` that actually ran.
"""

import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from app.providers import harness, mistral
from kriko.extract.grounding import loose_span
from kriko.research import BudgetExceeded
from kriko.research.base import Document, ResearchTask

#: What one run may spend when nobody named a ceiling. A quick look measured
#: $0.12 on `mistral-small-latest` (four searches) and $0.29 on
#: `mistral-large-latest` (nine). This covers the first with room for a
#: repair, and stops a runaway before it is a surprise.
DEFAULT_BUDGET_USD = 0.50

#: Said to every request, research or not: what the tool is, and that a
#: quote is checked against what it returned.
TOOLS = """
## Your tools, and how quotes are checked (this run)

Your only tool is **web search**. It can also open a result page. There is no
separate fetch tool, and no file or shell tool.

Report only urls that a search returned to you in this run. Copy each quote
word for word from the text the search returned for that url: the result's
snippet, or the page it opened. Each quote is checked against exactly that
text, and a quote that is not in it is dropped.
"""

#: Appended to `harness.CONTRACT`, and it overrides two lines of it. There is
#: no web fetch tool here, and `document_text` is not needed: the grounding
#: source is the search result itself.
NOTE = TOOLS + "`document_text` may be left empty.\n"


@dataclass(frozen=True)
class ApiAgent:
    """One agent reached over an API. Shaped like `harness.Harness` where the
    researcher reads it (`id`, `label`, `contract_note`), and nowhere else."""

    id: str
    label: str
    #: The `app/keys.py` provider that pays for it.
    key: str
    default_model: str
    #: The tool the provider bills per call, as `models.toml`'s `[tools.*]`
    #: table names it.
    search_tool: str
    #: Where it runs, shown where a CLI row shows its path.
    host: str
    contract_note: str = ""
    model_hint: str = ""
    #: What the Settings row says when the key is absent.
    install_hint: str = ""
    #: Where a key is made: the missing row's way out, where a CLI's row
    #: links its download page.
    key_url: str = ""


MISTRAL = ApiAgent(
    id="mistral-api",
    label="Mistral API",
    key="mistral",
    default_model=mistral.DEFAULT_MODEL,
    search_tool="web_search",
    host="api.mistral.ai",
    contract_note=NOTE,
    model_hint=(
        "Small answered a quick look in 9 s for about $0.12; Large took 46 s "
        "and opened more pages. Every search or page opened costs $0.03 on "
        "top of the tokens."
    ),
    install_hint="Add a Mistral key in Settings → Research.",
    # Checked 2026-09-29: answers, behind Mistral's login.
    key_url="https://console.mistral.ai/api-keys",
)

#: A closed roster, as `harness.KNOWN` is: each entry is an adapter somebody
#: wrote, not data that grows with coverage.
KNOWN: tuple[ApiAgent, ...] = (MISTRAL,)
BY_ID = {one.id: one for one in KNOWN}


def available(path: Path | None = None) -> list[ApiAgent]:
    """The agents whose key this installation has. Never raises: a broken
    env file is "none ready", not a crashed settings page."""
    from app import keys

    try:
        present = {one["id"] for one in keys.status(path) if one["present"]}
    except Exception:  # noqa: BLE001 — see the docstring
        return []
    return [one for one in KNOWN if one.key in present]


def models_for(agent: ApiAgent, home: Path | None = None) -> list[str]:
    """The catalogue's models for this agent's provider, its default first.

    Read off `models.toml` rather than listed here, so that a row the reader
    adds for a new model is selectable the day they add it.
    """
    from app import modelcatalogue

    rows = modelcatalogue.load(home)
    names = [name for name, row in rows.items() if row.get("provider") == agent.key]
    return sorted(names, key=lambda name: (name != agent.default_model, name))


class ApiAgentResearcher(harness.HarnessResearcher):
    """The harness plane's contract, answered over HTTP and grounded on what
    the search actually returned."""

    cost_basis = "per_token"

    def __init__(self, agent: ApiAgent, *, model: str = "",
                 timeout: float = mistral.TIMEOUT_SECONDS, converse=None,
                 home: Path | None = None):
        # An `ApiAgent` where a `Harness` is annotated: the parent reads only
        # `id`, `label` and `contract_note` off it on the paths this class
        # keeps, and `_run` — the one that spawns — is overridden.
        super().__init__(agent, timeout=timeout, model=model)  # type: ignore[arg-type]
        self.agent = agent
        #: The model that runs, not the agent's id. The CLI plane names the
        #: harness here because it cannot know the model; this plane can.
        self.model = model.strip() or agent.default_model
        self.search_provider = agent.label
        self._converse = converse or mistral.converse
        self._home = home
        #: What the provider billed, in dollars. `None` once any call could
        #: not be priced: an under-count reported as a total is the invented
        #: cost `models.toml` warns about. `_at_least` keeps the priced part
        #: for the budget check, which needs a number either way.
        self.spent: float | None = 0.0
        self._at_least = 0.0
        self._unpriced = False
        self.tokens_in: int | None = None
        self.tokens_out: int | None = None
        self.tool_calls = 0
        #: url -> the text the search tool returned for it, across every call
        #: this researcher made. The grounding source.
        self.sources: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        #: The queries the provider says it ran. More honest than the ones the
        #: model reports in its JSON, and so what `queries_run` is set to.
        self.searched: list[str] = []
        #: Findings refused because their quote was not in their url's text.
        self.dropped = 0

    # ── what the prompt says ────────────────────────────────────────────────

    def _budget(self) -> float:
        return self.budget_usd or DEFAULT_BUDGET_USD

    def _calls_allowed(self) -> int:
        price = self._search_price()
        if not price:
            return 0
        return max(1, int((self._budget() - self._at_least) // price))

    def _ceiling(self) -> str:
        """A ceiling in *searches*, as a sentence.

        A page count says nothing about dollars here: every search and every
        page the tool opens bills $0.03. The ceiling is a sentence, because
        the API has no switch for it. One call can overshoot it, and the meter
        reports what was actually billed.
        """
        calls = self._calls_allowed()
        return (
            f"\n## How much this run may spend\n\nAt most **{calls} searches "
            "and page opens in total**. Each one is billed to the reader. Stop "
            "there and report what you have.\n"
            if calls else ""
        )

    def _contract(self) -> str:
        return super()._contract() + self._ceiling()

    def ask(self, prompt: str) -> str:
        """`HarnessResearcher.ask`, told what its tool is and what it may spend.

        A CLI's `ask` carries neither: its own tools are its business, and its
        subscription is not metered. Here both are the run's.
        """
        return self._run(prompt + "\n" + TOOLS + self._ceiling())

    # ── one request ─────────────────────────────────────────────────────────

    def _run(self, prompt: str, on_line=None) -> str:
        if self._at_least >= self._budget():
            raise BudgetExceeded(
                f"{self.agent.label} has spent ${self._at_least:.2f} of this "
                f"run's ${self._budget():.2f}; no further request was sent")
        if self.check_cancelled is not None:
            self.check_cancelled()
        self._echo(f"asking {self.agent.label} ({self.model}); it searches "
                   "the web itself")
        box: dict = {}

        def call():
            try:
                box["reply"] = self._converse(prompt, model=self.model,
                                              timeout=self.timeout)
            except Exception as error:  # noqa: BLE001 — re-raised below
                box["error"] = error

        started = time.monotonic()
        worker = threading.Thread(target=call, name="kriko-api-agent", daemon=True)
        worker.start()
        # Cancel is polled while the request is out, as the CLI plane polls
        # between output lines. A request already sent cannot be recalled:
        # the provider bills it whether or not anyone reads the answer, and
        # the meter cannot count what never came back.
        while worker.is_alive():
            worker.join(self._cancel_tick)
            if worker.is_alive() and self.check_cancelled is not None:
                self.check_cancelled()
        if "error" in box:
            raise box["error"]
        reply = box["reply"]
        self._account(reply)
        for query in reply.queries:
            self._echo(f"searched: {query}")
        for url, row in reply.sources.items():
            known = self.sources.get(url, "")
            if row["text"] and row["text"] not in known:
                self.sources[url] = (known + "\n\n" + row["text"]).strip()
            self._titles.setdefault(url, row["title"])
        self.searched += [one for one in reply.queries if one not in self.searched]
        cost = f"${self.spent:.2f}" if self.spent is not None else "cost unknown"
        self._echo(f"{self.agent.label} answered in {time.monotonic() - started:.0f} s: "
                   f"{max(reply.tool_calls, len(reply.queries))} search(es), "
                   f"{len(reply.sources)} result(s), {cost}")
        self.transcript = (reply.text or reply.error)[-harness.TRANSCRIPT_TAIL:]
        if reply.error:
            raise RuntimeError(f"{self.agent.label}: {reply.error}")
        return reply.text

    def _account(self, reply) -> None:
        from app import modelcatalogue

        for name in ("tokens_in", "tokens_out"):
            value = getattr(reply, name)
            if value is not None:
                setattr(self, name, (getattr(self, name) or 0) + value)
        if self.tokens_in is not None or self.tokens_out is not None:
            self.tokens_used = (self.tokens_in or 0) + (self.tokens_out or 0)
        # Billed calls are at least the searches the reply shows. A `usage`
        # block that omits `connectors` would otherwise make four $0.03
        # searches free.
        calls = max(reply.tool_calls, len(reply.queries))
        self.tool_calls += calls
        tokens = (
            None if reply.tokens_in is None or reply.tokens_out is None
            # No usage block is "cannot count". Pricing it as zero tokens
            # would report a paid run as $0.00.
            else modelcatalogue.price(self.model, reply.tokens_in, reply.tokens_out, self._home)
        )
        per_call = self._search_price()
        tools = calls * per_call if per_call is not None else None
        if tokens is None or (calls and tools is None):
            self._unpriced = True
        self._at_least += (tokens or 0.0) + (tools or 0.0)
        self.spent = None if self._unpriced else round(self._at_least, 6)
        self.cost_usd = self.spent

    def _search_price(self) -> float | None:
        from app import modelcatalogue

        return modelcatalogue.tool_price(self.agent.key, self.agent.search_tool, self._home)

    # ── grounding ───────────────────────────────────────────────────────────

    def gather(self, task: ResearchTask) -> list[Document]:
        """`HarnessResearcher.gather`, then every quote checked against the
        search text for its own url.

        A kept quote is replaced with the source's own characters
        (`loose_span`). Ingestion's check is exact, and a model that re-typed
        an apostrophe should not lose a true finding over it. The document
        is the search text, never the agent's paste, so the stored quote is
        a substring of what the provider actually returned.
        """
        super().gather(task)
        if self.searched:
            self.queries_run = list(self.searched)
        kept: dict[str, list] = {}
        documents = []
        for url, findings in self._by_url.items():
            source = self.sources.get(url, "")
            for finding in findings:
                span = loose_span(source, finding.quote) if source else ""
                if not span:
                    self.dropped += 1
                    continue
                kept.setdefault(url, []).append(replace(finding, quote=span))
            if url in kept:
                documents.append(Document(
                    url=url, text=source, site_or_channel=harness._site(url),
                    title=self._titles.get(url) or kept[url][0].title,
                    source_type="page"))
        self._by_url = kept
        if self.dropped:
            self.note = (f"{self.dropped} finding(s) dropped: the quote was not "
                         "in the search result for its url")
        if not documents and not self.note:
            self.note = f"{self.agent.label} reported no usable findings"
        return documents
