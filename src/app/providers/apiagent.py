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
from collections.abc import Callable
from collections import deque
import time
from dataclasses import dataclass, replace
from pathlib import Path

from app.providers import harness, mistral
from app.providers._http import StreamCancelled
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

OPENAI_COMPATIBLE = ApiAgent(
    id="openai-api",
    label="OpenAI-compatible API",
    key="openai",
    default_model="gpt-4o-mini",
    search_tool="web_search",
    host="custom endpoint",
    contract_note=NOTE,
    model_hint="Uses the OpenAI-compatible endpoint and key configured in Settings.",
    install_hint="Add an OpenAI or compatible API key in Settings → Keys.",
    key_url="https://platform.openai.com/api-keys",
)

KRIKO_AGENT = ApiAgent(
    id="kriko-agent",
    label="Kriko Agent · Soon",
    key="mercury",
    default_model="mercury-2.5",
    search_tool="deepseek_search",
    host="api.inceptionlabs.ai + api.deepseek.com",
    contract_note=(
        "\n\n## Kriko Agent tools\n\n"
        "Your tools are search and fetch. Search uses DeepSeek Search and "
        "returns result URLs plus inline page text where available. Fetch reads "
        "a URL returned by search. Both are read-only. Use the page text "
        "returned by these tools as the only source for verbatim quotes.\n"
    ),
    model_hint=(
        "Experimental preview: Mercury 2.5 for research and DeepSeek Search/Fetch "
        "for retrieval. Uses your own provider keys on this computer; "
        "no shared Kriko credentials are included."
    ),
    install_hint=(
        "Add both MERCURY_API_KEY and DEEPSEEK_API_KEY in Settings → Research."
    ),
    key_url="https://platform.inceptionlabs.ai/",
)

#: A closed roster, as `harness.KNOWN` is: each entry is an adapter somebody
#: wrote, not data that grows with coverage.
KNOWN: tuple[ApiAgent, ...] = (MISTRAL, OPENAI_COMPATIBLE, KRIKO_AGENT)
BY_ID = {one.id: one for one in KNOWN}


def available(path: Path | None = None) -> list[ApiAgent]:
    """The agents whose key this installation has. Never raises: a broken
    env file is "none ready", not a crashed settings page."""
    from app import keys

    try:
        present = {one["id"] for one in keys.status(path) if one["present"]}
    except Exception:  # noqa: BLE001 — see the docstring
        return []
    return [
        one for one in KNOWN
        if one.key in present
        and (one.id != KRIKO_AGENT.id or "deepseek" in present)
    ]


def models_for(agent: ApiAgent, home: Path | None = None) -> list[str]:
    """The provider's live list plus priced catalogue entries, default first."""
    from app import modelcatalogue, modeldiscovery

    rows = modelcatalogue.load(home)
    names = {name for name, row in rows.items() if row.get("provider") == agent.key}
    names.update(modeldiscovery.cached().get(agent.key, []))
    return sorted(names, key=lambda name: (name != agent.default_model, name))


def openai_compatible_converse(prompt: str, *, model: str = "", timeout: float = 45.0,
                               search: bool = True, app_state_path=None,
                               cancel_event=None):
    """Answer through an OpenAI-compatible endpoint, optionally using search.

    Function calling is the common OpenAI wire shape. Search itself remains
    this installation's selected Exa or Tavily provider, and every opened page
    is returned as grounding text just as it is for the Mistral API agent.
    """
    import json
    import os

    from app import keys, prefs
    from app.providers import fetch, llm
    from app.providers._http import post_json_or_why
    from app.web import state

    api_key = keys.require("openai")
    base_url = os.environ.get("LLM_BASE_URL") or llm.DEFAULT_BASE_URL
    if app_state_path is not None:
        conn = state.connect(app_state_path)
        try:
            base_url = prefs.read(conn).get(prefs.LLM_BASE_URL) or base_url
            search_provider = prefs.read(conn).get(prefs.SEARCH)
        finally:
            conn.close()
    else:
        search_provider = ""
    endpoint = base_url.rstrip("/") + "/chat/completions"
    messages = [{"role": "user", "content": prompt}]
    have_search = bool(keys.search_providers())
    tools = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and open a few result pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["query"],
            },
        },
    }] if search and have_search else []
    reply = mistral.Reply()
    searcher = reader = None
    if tools:
        from app.providers import _searcher

        searcher, search_provider = _searcher(app_state_path, search_provider or "")
        reader = fetch.reader()
    call_count = 0
    for _round in range(5):
        if cancel_event is not None and cancel_event.is_set():
            raise StreamCancelled("provider request canceled")
        payload = {
            "model": model or OPENAI_COMPATIBLE.default_model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 2048,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body, why = post_json_or_why(
            endpoint, payload, {"authorization": f"Bearer {api_key}"}, timeout=timeout)
        if why:
            reply.error = why
            return reply
        if not isinstance(body, dict):
            reply.error = "OpenAI-compatible endpoint returned an invalid response"
            return reply
        usage = body.get("usage")
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) and prompt_tokens >= 0:
                reply.tokens_in = (reply.tokens_in or 0) + prompt_tokens
            else:
                reply.usage_complete = False
            completion_tokens = usage.get("completion_tokens")
            if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool) and completion_tokens >= 0:
                reply.tokens_out = (reply.tokens_out or 0) + completion_tokens
            else:
                reply.usage_complete = False
        else:
            reply.usage_complete = False
        choices = body.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        if not isinstance(message, dict):
            reply.error = "OpenAI-compatible endpoint returned no message"
            return reply
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            reply.text = str(message.get("content") or "").strip()
            if not reply.text:
                reply.error = "OpenAI-compatible endpoint returned no text"
            return reply
        call_count += len(calls)
        if call_count > 8:
            reply.error = "OpenAI-compatible endpoint exceeded the search call limit"
            return reply
        messages.append(message)
        if searcher is None or reader is None:
            reply.error = "Endpoint requested web search while tools were disabled"
            return reply
        for call in calls:
            if cancel_event is not None and cancel_event.is_set():
                raise StreamCancelled("provider request canceled")
            function = call.get("function") if isinstance(call, dict) else None
            name = str((function or {}).get("name") or "") if isinstance(function, dict) else ""
            call_id = str(call.get("id") or "") if isinstance(call, dict) else ""
            if name != "web_search":
                messages.append({"role": "tool", "tool_call_id": call_id,
                                 "content": json.dumps({"error": "unsupported tool"})})
                continue
            try:
                args = json.loads((function or {}).get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            query = str(args.get("query") or "").strip() if isinstance(args, dict) else ""
            result_rows: list[dict] = []
            if not query:
                pass
            else:
                reply.queries.append(query)
                reply.tool_calls += 1
                try:
                    hits = searcher(query, max(1, min(int(args.get("limit") or 3), 5)))
                except Exception:  # noqa: BLE001 — the model can finish without search
                    hits = []
                for hit in hits:
                    if cancel_event is not None and cancel_event.is_set():
                        raise StreamCancelled("provider request canceled")
                    url = str(hit.get("url") or "").strip()
                    if not url:
                        continue
                    try:
                        text = str(reader(url) or "")[:mistral.MAX_SOURCE_CHARS]
                    except Exception:  # noqa: BLE001 — one bad page is a missed source
                        text = ""
                    if not text:
                        continue
                    title = str(hit.get("title") or "").strip()
                    previous = reply.sources.setdefault(url, {"title": title, "text": text})
                    result_rows.append({"url": url, "title": previous["title"], "content": previous["text"]})
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(
                    {"error": "query is required", "results": []}
                    if not query else {"results": result_rows},
                    ensure_ascii=False,
                ),
            })
    reply.error = "OpenAI-compatible endpoint exceeded the search tool-call limit"
    return reply


class ApiAgentResearcher(harness.HarnessResearcher):
    """The harness plane's contract, answered over HTTP and grounded on what
    the search actually returned."""

    cost_basis = "per_token"

    def __init__(self, agent: ApiAgent, *, model: str = "",
                 timeout: float = mistral.TIMEOUT_SECONDS, converse=None,
                 home: Path | None = None, app_state_path=None):
        # An `ApiAgent` where a `Harness` is annotated: the parent reads only
        # `id`, `label` and `contract_note` off it on the paths this class
        # keeps, and `_run` — the one that spawns — is overridden.
        super().__init__(agent, timeout=timeout, model=model)  # type: ignore[arg-type]
        self.agent = agent
        #: The model that runs, not the agent's id. The CLI plane names the
        #: harness here because it cannot know the model; this plane can.
        self.model = model.strip() or agent.default_model
        self.search_provider = ("DeepSeek Search"
                                if agent.id == KRIKO_AGENT.id else agent.label)
        self.thoroughness = 50
        self.validation_sensitivity = 50
        self._cache_path = None
        if converse is not None:
            self._converse = converse
        elif agent.key == "openai":
            self._converse = lambda prompt, **kw: openai_compatible_converse(
                prompt, **kw, app_state_path=app_state_path)
        elif agent.id == KRIKO_AGENT.id:
            from app.providers import kriko_agent

            self._converse = kriko_agent.converse
        else:
            self._converse = mistral.converse
        # Injected test/tool adapters keep their established complete-reply
        # shape. The built-in Mistral adapter has a verified SSE endpoint.
        if converse is None and agent.id == KRIKO_AGENT.id:
            from app.providers import kriko_agent

            if app_state_path is not None:
                from app import prefs
                from app.web import state

                try:
                    conn = state.connect(app_state_path)
                    try:
                        tuning = prefs.kriko_agent_tuning(conn)
                    finally:
                        conn.close()
                    self.thoroughness = tuning["thoroughness"]
                    self.validation_sensitivity = tuning["validation_sensitivity"]
                    self._cache_path = str(
                        Path(app_state_path).parent / "cache" / "kriko-agent.sqlite3"
                    )
                except Exception:  # noqa: BLE001 — defaults keep a run usable
                    pass

            self._stream_converse: Callable[..., mistral.Reply | None] | None = (
                lambda prompt, **kw: kriko_agent.converse(
                prompt, max_tool_calls=self._calls_allowed(),
                thoroughness=self.thoroughness,
                validation_sensitivity=self.validation_sensitivity,
                cache_path=self._cache_path, **kw))
        else:
            self._stream_converse = (mistral.converse_stream
                                     if converse is None and agent.key == "mistral" else None)
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
        self.usage_complete = True
        self.tool_calls = 0
        self.retrieval_requests = 0
        self.cache_hits = 0
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

    def ask(self, prompt: str, *, allow_tools: bool = True) -> str:
        """One completion with an explicit web-tool grant.

        Research keeps the existing search-enabled contract by default. A
        classification call can request a tool-less completion; that path
        omits the web instructions and spending-on-search clause and sends no
        `web_search` tool to Mistral. Prompt wording alone is not a permission
        boundary.
        """
        if allow_tools:
            return self._run(
                prompt + "\n" + TOOLS + self._ceiling(), search=True)
        return self._run(prompt, search=False)

    # ── one request ─────────────────────────────────────────────────────────

    def _run(self, prompt: str, on_line=None, *, search: bool = True) -> str:
        if self._at_least >= self._budget():
            raise BudgetExceeded(
                f"{self.agent.label} has spent ${self._at_least:.2f} of this "
                f"run's ${self._budget():.2f}; no further request was sent")
        if self.check_cancelled is not None:
            self.check_cancelled()
        self._echo(
            f"asking {self.agent.label} ({self.model}); "
            + ("it searches the web itself" if search else "web tools are disabled")
        )
        box: dict = {}
        pending: deque[str] = deque()
        pending_chars = 0
        pending_lock = threading.Lock()
        stop_deltas = threading.Event()

        def queue_delta(text: str) -> None:
            nonlocal pending_chars
            if stop_deltas.is_set():
                raise StreamCancelled("provider stream canceled")
            if not text:
                return
            with pending_lock:
                pending.append(text)
                pending_chars += len(text)
                while pending_chars > harness.LIVE_DRAFT_CHARS and pending:
                    excess = pending_chars - harness.LIVE_DRAFT_CHARS
                    old = pending.popleft()
                    pending_chars -= len(old)
                    if len(old) > excess:
                        pending.insert(0, old[excess:])
                        pending_chars += len(old) - excess

        def publish_deltas() -> None:
            nonlocal pending_chars
            with pending_lock:
                text = "".join(pending)
                pending.clear()
                pending_chars = 0
            if text:
                # Reuse the same prose/JSON/fence filter and bounded draft
                # buffer as the CLI path. Run this on the job thread so the
                # Progress callback uses its SQLite connection on its owner.
                self._append_live_text(text)

        def call():
            try:
                if self._stream_converse is not None:
                    box["reply"] = self._stream_converse(
                        prompt, model=self.model, timeout=self.timeout,
                        on_text=queue_delta, cancel_event=stop_deltas,
                        search=search,
                    )
                else:
                    if search:
                        box["reply"] = self._converse(
                            prompt, model=self.model, timeout=self.timeout,
                            **({"cancel_event": stop_deltas} if self.agent.key == "openai" else {}))
                    else:
                        box["reply"] = self._converse(
                            prompt, model=self.model, timeout=self.timeout,
                            search=False,
                            **({"cancel_event": stop_deltas} if self.agent.key == "openai" else {}))
            except Exception as error:  # noqa: BLE001 — re-raised below
                box["error"] = error

        started = time.monotonic()
        worker = threading.Thread(target=call, name="kriko-api-agent", daemon=True)
        worker.start()
        # Cancel is polled while the request is out, as the CLI plane polls
        # between output lines. A request already sent cannot be recalled:
        # the provider bills it whether or not anyone reads the answer, and
        # the meter cannot count what never came back.
        last_cancel_check = started
        try:
            while worker.is_alive():
                worker.join(0.05)
                publish_deltas()
                now = time.monotonic()
                if (worker.is_alive() and self.check_cancelled is not None
                        and now - last_cancel_check >= self._cancel_tick):
                    self.check_cancelled()
                    last_cancel_check = now
            publish_deltas()
        finally:
            stop_deltas.set()
            publish_deltas()
            if self.on_text is not None and self._live_published:
                try:
                    self.on_text("")
                except Exception:  # noqa: BLE001 — a live status cannot lose a run
                    pass
            self._live_parts.clear()
            self._live_chars = 0
            self._live_detector_tail = ""
            self._live_suppressed = False
            self._live_published = ""
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
        billed_calls = (reply.billed_tool_calls
                        if isinstance(reply.billed_tool_calls, int)
                        and not isinstance(reply.billed_tool_calls, bool)
                        else max(reply.tool_calls, len(reply.queries)))
        retrieval_requests = (reply.retrieval_requests
                              if isinstance(reply.retrieval_requests, int)
                              and not isinstance(reply.retrieval_requests, bool)
                              else billed_calls)
        self._echo(f"{self.agent.label} answered in {time.monotonic() - started:.0f} s: "
                   f"{retrieval_requests} retrieval request(s), {billed_calls} billable, "
                   f"{len(reply.sources)} result(s), {reply.cache_hits} cached, {cost}")
        self.transcript = (reply.text or reply.error)[-harness.TRANSCRIPT_TAIL:]
        if reply.error:
            raise RuntimeError(f"{self.agent.label}: {reply.error}")
        return reply.text

    def _account(self, reply) -> None:
        from app import modelcatalogue

        if not getattr(reply, "usage_complete", True):
            self.usage_complete = False
            self._unpriced = True

        for name in ("tokens_in", "tokens_out"):
            value = getattr(reply, name)
            if value is not None:
                setattr(self, name, (getattr(self, name) or 0) + value)
        if self.tokens_in is not None or self.tokens_out is not None:
            self.tokens_used = (self.tokens_in or 0) + (self.tokens_out or 0)
        # Billed calls are at least the searches the reply shows. A `usage`
        # block that omits `connectors` would otherwise make four $0.03
        # searches free.
        calls = (reply.billed_tool_calls
                 if isinstance(reply.billed_tool_calls, int)
                 and not isinstance(reply.billed_tool_calls, bool)
                 else max(reply.tool_calls, len(reply.queries)))
        self.tool_calls += calls
        self.cache_hits += max(0, int(getattr(reply, "cache_hits", 0) or 0))
        requests = (reply.retrieval_requests
                    if isinstance(reply.retrieval_requests, int)
                    and not isinstance(reply.retrieval_requests, bool)
                    else calls)
        self.retrieval_requests += requests
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
                if self.agent.id == KRIKO_AGENT.id:
                    from app.providers.kriko_agent import validated_quote

                    span = validated_quote(
                        source, finding.quote, self.validation_sensitivity,
                    ) if source else ""
                else:
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
