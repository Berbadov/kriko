"""An `ask` for the local model: the quick look and the pack author with no CLI.

The coding agents that answer `ask(prompt)` bring their own web search. A model
served from this machine does not: it reads what it is given. So this adapter
does the legwork a CLI does for itself, in three plain steps, each one a socket
the local plane already owns:

1. the model proposes a few search queries for what the prompt describes;
2. the search service answers them (OpenSERP, else Exa's hosted search) and
   the stock reader fetches the top pages;
3. the model answers the prompt with those pages beside it.

The pages it read are kept by address in `sources`, the same slot the API
agent fills, so `quicklook.parse` can require every quote to be *in* the page
it cites. A small model does not get to write a risk nobody published: a quote
that is not on a fetched page is dropped, and so is a risk with no page.

Nothing here decides what the answer is worth. It is the same brief, the same
reply shape and the same grounding as every other door; only the reader of the
web differs.
"""

import json
import re
from collections.abc import Callable
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from app.providers.local_inference import LocalInferenceError
from app.providers import local_components
from app.providers.local_components import evidence, identity
from app.providers.local_components import plan as plan, triage as triage, verify as verify

REASONING_EFFORT = "none"

#: What a quick check searches for beside the product's name. The first two
#: are the long-standing pair; the others reach forums and repair pages, the
#: sources a single review site cannot stand in for.
QUICK_ANGLES = ("problems owner reports", "failures review",
                "common issues forum discussion", "known defects repair")
REPLY_MAX_TOKENS = 1024

from kriko.research.politeness import LocalSearchError
from kriko.research.window import focus

#: Queries proposed, hits taken per query and pages read in all. Small on
#: purpose: each page costs a model call's worth of context on a CPU.
QUERIES = 3
HITS_PER_QUERY = 5
MAX_PAGES = 6
#: Characters of each page shown to the model, and kept as the text its
#: quotes are checked against. The two are the same on purpose: a quote from
#: beyond what the model saw could only have been invented.
PAGE_CHARS = 6000
#: Seconds the read waits for pages once the search is done. A page behind a
#: bot wall walks the whole fetch ladder (plain fetch, two hosted readers, a
#: headless browser), which can take minutes, and the model should not wait
#: on the slowest page when the others are in. A page still out at the
#: deadline is a miss, exactly as an unreadable one.
READ_DEADLINE = 25.0
# Quick Look is interactive: gather a first page set promptly, while still
# leaving enough of the budget to read those pages. Deep research keeps the
# longer deadlines above.
QUICK_SEARCH_TIMEOUT = 8.0
QUICK_SEARCH_PACE_INTERVAL = 1.0
QUICK_SEARCH_DEADLINE = 12.0
QUICK_READ_DEADLINE = 15.0
#: Candidate pages asked for beyond `MAX_PAGES`, so a page that is slow or
#: unreadable is replaced by the next one instead of leaving a gap.
SPARE_PAGES = 3
HEDGE_AFTER = 4.0
HEDGED_PAGES = 2
#: Text shorter than a sentence or so is a refusal, a cookie wall or an empty
#: shell, not a page: it is a miss, so a spare takes its place.
MIN_PAGE_CHARS = 80
#: The least of a page worth showing. When the model's context cannot give
#: every page this much, fewer pages are shown, each one whole enough to
#: quote from, rather than all of them as fragments.
MIN_SHARE = 1200
#: Characters of the task the planner reads. The product and the listing
#: are at the top; the reply format below them is where a small model picks
#: up a url and offers it as a "query".
PLAN_CHARS = 1500
#: A query longer than this is a sentence, not a search.
QUERY_WORDS = 15


def _is_index_page(url: str) -> bool:
    """A section front page, not a thread or a document.

    Measured on a Ford Focus look: four of the five pages read were
    `focusfanatics.com/forums/`, `focusst.org/`, a manuals index and a forum
    root. They pass the relevance check because every thread title on them
    names the product, and then the extractor can only find thread titles, so
    the look spends four evidence passes on doors. Shallow and digit-free is
    the shape of a door in every site; the rule is the address, not a list of
    sites.
    """
    from urllib.parse import urlsplit

    path = urlsplit(str(url or "")).path.strip("/")
    if not path:
        return True
    segments = [part for part in path.split("/") if part]
    if len(segments) > 1:
        return False
    return not any(char.isdigit() for char in segments[0]) and len(segments[0]) <= 30

QUERY_SCHEMA = {"type": "array", "items": {"type": "string"}}
QUICK_SCHEMA: dict = {"type": "object", "properties": {
    "assumed": {"type": "string"}, "category": {"type": "string"}, "pack": {"type": "string"},
    "risks": {"type": "array", "items": {"type": "object", "properties": {
        key: {"type": "string"} for key in ("title", "why", "check", "severity", "url", "quote", "evidence_id")},
        "required": ["title", "evidence_id"]}},
    "specs": {"type": "array", "items": {"type": "object", "properties": {
        key: {"type": "string"} for key in ("name", "value", "url")}, "required": ["name", "value", "url"]}}},
    "required": ["risks", "specs"]}
VERIFY_SCHEMA = {"type": "object", "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "properties": {"index": {"type": "integer"}, "supported": {"type": "boolean"},
                                      "reason": {"type": "string"}}, "required": ["index", "supported", "reason"]}}}, "required": ["verdicts"]}

_QUERY_ASK = (
    "You are choosing web searches. Read the task below and reply with ONLY a "
    "JSON array of {n} short web search queries that would find documented "
    "problems, failures and owner reports about the product it names. No "
    "prose.\n\n## Task\n\n{task}"
)

_QUERY_RETRY = (
    "That reply was not a list of web search queries. Reply with ONLY a JSON "
    "array of {n} short search queries (plain words, no URLs), for example "
    '["first query", "second query"].\n\n## Task\n\n{task}'
)

_PAGES_HEAD = (
    "\n\n## Pages you fetched\n\n"
    "These are the only sources you have. Cite only these URLs, exactly. Every "
    "quote must be copied verbatim from the page it cites. If the pages do not "
    "support a claim, leave it out rather than guess.\n\n"
)


class LocalAsker:
    """`ask(prompt) -> str`, answering from pages it fetched itself.

    Shaped like the harness researchers so the jobs that `ask` take it without
    knowing the difference: `on_action`, `check_cancelled` and `replies` are
    set by the job, `sources` and `search_provider` are read back.
    """

    name = "local"
    cost_basis = "self_hosted"

    def __init__(self, plan, complete, search, fetch, *, model: str,
                 search_provider: str, url: str = "",
                 given_queries: list[str] | None = None,
                 parallel_search: bool = False,
                 given_sources: dict[str, str] | None = None,
                 requested_specs: list[str] | None = None,
                 output_language: str = "auto", search_language: str = "en"):
        self.output_language = output_language
        self.search_language = search_language
        self.coverage: dict = {}
        self.search_coverage: dict = {}
        self.page_titles: dict[str, str] = {}
        self.relevant_sources: dict[str, str] = {}
        self.given_sources = given_sources
        self.requested_specs = requested_specs
        self.metrics: list[dict] = []
        self.given_queries = [str(one).strip() for one in (given_queries or [])
                              if str(one).strip()]
        #: True only for a hosted search service built to take concurrent
        #: requests. A local scraper (OpenSERP) asks a public search engine
        #: from the reader's own address, and a burst there is how a run
        #: earns a CAPTCHA, so it stays one query at a time.
        self.parallel_search = parallel_search
        self._plan = _MeasuredSocket(plan, self, "plan")
        self._complete = self._plan if plan is complete else _MeasuredSocket(complete, self, "answer")
        self._search = search
        self._fetch = fetch
        self.model = model
        self.search_provider = search_provider
        self.url = url
        self.sources: dict[str, str] = {}
        self._evidence: dict[str, tuple[str, str]] = {}
        self.on_action: Callable[[str], None] | None = None
        self.check_cancelled: Callable[[], None] | None = None
        #: Set by a job that wants the answer as it is written (`app/followup.py`).
        self.on_text: Callable[[str], None] | None = None
        self.replies = None
        self.note = ""
        self.max_pages = MAX_PAGES
        self.runtime: dict = {}
        self.source_instructions = ""
        self.identity = ""
        #: The stage the next completion belongs to. `local_pipeline` sets it
        #: around each structured call, so one flat "answer" row does not stand
        #: for the twenty calls a quick look makes (`_MeasuredSocket._invoke`).
        self._stage_hint = ""
        self.telemetry: dict = {"queries": [], "stages": [], "repairs": 0}

    @property
    def tokens_used(self) -> int | None:
        return self._tokens("tokens_used")

    @property
    def tokens_in(self) -> int | None:
        return self._tokens("tokens_in")

    @property
    def tokens_out(self) -> int | None:
        return self._tokens("tokens_out")

    @property
    def usage_complete(self) -> bool:
        return all(getattr(part, "usage_complete", True)
                   for part in (self._plan, self._complete))

    def _tokens(self, key: str) -> int | None:
        values = []
        for part in {id(self._plan): self._plan,
                     id(self._complete): self._complete}.values():
            value = getattr(part, key, None)
            if isinstance(value, int) and not isinstance(value, bool):
                values.append(value)
        return sum(values) if values else None

    def _measured(self, stage, socket, call):
        before = {key: getattr(socket, key, None)
                  for key in ("tokens_in", "tokens_out", "tokens_used")}
        started = time.perf_counter()
        failed = False
        failure = ""
        # Said *before* the wait, not after it. A local model can spend two
        # minutes in one completion, and a stage table that only learns about
        # it when it ends shows a console that looks hung for exactly as long.
        self._say(f"stage {stage} start")
        try:
            return call()
        except Exception as error:
            failed = True
            failure = f"{type(error).__name__}: {error}"[:200]
            raise
        finally:
            row = {"stage": stage, "ms": round(
                (time.perf_counter() - started) * 1000, 3), "failed": failed}
            for key, value in before.items():
                now = getattr(socket, key, None)
                row[key] = (now - (value or 0) if getattr(socket, "last_usage_complete", True)
                            and isinstance(now, int)
                            and not isinstance(now, bool) else None)
            if failure:
                row["error"] = failure
            self.metrics.append(row)
            self._say(self._stage_line(row))

    def _stage_line(self, row: dict) -> str:
        """One stage, as a line the log and the console both read.

        The shape is a contract rather than prose: `app/tui/local.py` parses it
        into the stage table, and the terminal and the JSON report of a bench
        run are the same numbers because they are the same line. A prefix no
        other log line uses ("stage "), a name with no spaces, then one of
        `start`, `done`, `failed`.
        """
        head = f"stage {row['stage']}"
        if row.get("failed"):
            return (f"{head} failed {row['ms'] / 1000:.3f}s"
                    + (f": {row['error']}" if row.get("error") else ""))
        measured = [f"{key.removeprefix('tokens_')}={row[key]}"
                    for key in ("tokens_in", "tokens_out")
                    if row.get(key) is not None]
        return f"{head} done {row['ms'] / 1000:.3f}s" + (
            " " + " ".join(measured) if measured else "")

    def _record(self, row: dict) -> dict:
        """Keep one already-timed stage row, and say it."""
        self.metrics.append(row)
        self._say(self._stage_line(row))
        return row

    def _phase(self, stage: str, started: float, **fields) -> dict:
        """Record a phase that has no socket of its own (search, page reads)."""
        return self._record({"stage": stage,
                             "ms": round((time.perf_counter() - started) * 1000, 3),
                             "failed": False, **fields})

    def _say(self, line: str) -> None:
        self.telemetry["stages"].append({"elapsed_ms": int((time.monotonic() - getattr(self, "_started", time.monotonic())) * 1000), "message": line})
        if self.on_action is not None:
            self.on_action(line)

    def _check(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()

    def ask(self, prompt: str) -> str:
        from app.workcontract import WORK_CONTRACT
        if WORK_CONTRACT not in prompt:
            prompt += "\n\n" + WORK_CONTRACT
        self.sources = {}
        self.relevant_sources = {}
        self.page_titles = {}
        self.search_coverage = {}
        if prompt.startswith("# Quick look:"):
            return self.quicklook(prompt, product=identity.product_line(prompt))
        if self.given_sources is not None:
            delegated = local_components.LocalAsker(
                self._plan.socket, self._complete.socket, self._search, self._fetch,
                model=self.model, search_provider=self.search_provider, url=self.url,
                given_queries=self.given_queries, parallel_search=self.parallel_search,
                given_sources=self.given_sources, requested_specs=self.requested_specs)
            delegated.on_action = self.on_action
            delegated.check_cancelled = self.check_cancelled
            delegated.replies = self.replies
            try:
                return delegated.ask(prompt)
            finally:
                self.sources = delegated.sources
                self.metrics = delegated.metrics
                self.verification = delegated.verification
                self.telemetry.update(stages=delegated.metrics, verification=delegated.verification)
        self.metrics = []
        self._started = time.monotonic()
        self._check()
        self._say(f"asking {self.model} at {self.url or 'this machine'}; "
                  f"searching through {self.search_provider}")
        language = ("the language of the request" if self.output_language == "auto"
                    else self.output_language)
        prompt += (f"\nWrite summaries and advice in {language}; preserve exact source quotes, "
                   "product codes, URLs and JSON keys.")
        queries = identity.anchor_queries(prompt, self._queries(prompt))
        self.telemetry["queries"] = queries
        self._say("searching: " + "; ".join(queries))
        pages = self._read(queries)
        if not pages:
            raise LocalInferenceError(
                f"no page could be read through {self.search_provider} for: "
                + "; ".join(queries)
                + ". Check the internet connection, or start a local "
                "search service (OpenSERP on 127.0.0.1:7000).", code="no_evidence")
        self._say(f"read {len(pages)} page(s): "
                  + ", ".join(url for url, _ in pages))
        self._check()
        pages = self._fit(prompt, pages, queries)
        blocks = self._blocks(pages) if self.identity else "\n\n".join(f"### URL: {url}\n{text}" for url, text in pages)
        answer = prompt + _PAGES_HEAD + blocks + self._reply_budget()
        if self.on_text is not None:
            return self._complete.stream(answer, self.on_text)
        return self._complete(answer)

    def ask_quick(self, product: str, *, principle: str = "", page: dict | None = None,
                  packs: str = "", attributes: str = "") -> str:
        from app.quicklook import brief
        return self.quicklook(brief(product, principle, page, packs, attributes,
                                    max_sources=self.max_pages), product=product, page=page)

    def name_product(self, product: str, page: dict | None = None) -> str:
        """The product a listing title names, without the seller's words, or "".

        The quick look's identity step, alone: one structured call, and the
        name is kept only when every word of it is in the title or the
        listing (`parse_identity`). "" when it is the title itself (#181).
        """
        from app import pagefacts
        from app.providers.local_identity import (
            IDENTITY_SCHEMA, clean_product_name, fold, identity_prompt, parse_identity)
        from app.providers.local_pipeline import QuickLookPipeline

        page = page or {}
        listing = pagefacts.block(pagefacts.clean(page.get("facts"), page.get("description", "")))
        coverage = self.coverage
        try:
            raw = QuickLookPipeline(self)._call(
                identity_prompt(product, listing, self.search_language), IDENTITY_SCHEMA)
        finally:
            self.coverage = coverage
        name = parse_identity(json.dumps(raw), product, listing).canonical_name
        return name if fold(name) != fold(clean_product_name(product)) else ""

    def quicklook(self, prompt: str, *, product: str, page: dict | None = None) -> str:
        from app.providers.local_pipeline import QuickLookPipeline
        self.metrics = []
        self._started = time.monotonic()
        self.verification = {}
        self.identity = ""
        self.page_titles = {}
        try:
            return QuickLookPipeline(self).run(prompt, product, page)
        finally:
            self.relevant_sources = dict(self.sources)
            self._refresh_runtime()
            self.telemetry.update(coverage=self.coverage, identity=self.identity,
                                  stages=self.metrics, runtime=self.runtime)

    def _refresh_runtime(self) -> None:
        """Read Ollama's actual device allocation while the model is still loaded."""
        if not self.runtime or self.runtime.get("runtime") != "Ollama":
            return
        from app.localruntime import inspect

        current = inspect(self.url, "Ollama", self.model,
                          self.runtime.get("settings", {}))
        self.runtime.update(current)

    def _blocks(self, pages: list[tuple[str, str]]) -> str:
        # The model selects an evidence passage; the engine copies its bytes.
        # No fuzzy quote repair or translation can create a source sentence.
        self._evidence = {}
        blocks = []
        for url, text in pages:
            blocks.append(f"SOURCE URL: {url}")
            pieces = evidence.quotes(text, self.identity, limit=48)
            for piece in pieces:
                piece = piece.strip()
                if len(piece) < 30:
                    continue
                # Fixed-size slices also cover pages whose reader emits one line.
                for start in range(0, len(piece), 480):
                    quote = piece[start:start + 480]
                    if len(quote) < 30:
                        continue
                    evidence_id = f"E{len(self._evidence) + 1}"
                    self._evidence[evidence_id] = (url, quote)
                    blocks.append(f"[{evidence_id}] {quote}")
        if self.identity:
            import copy
            schema = copy.deepcopy(QUICK_SCHEMA)
            risk = schema["properties"]["risks"]["items"]
            risk["properties"] = {key: {"type": "string", "maxLength": 180}
                                  for key in ("title", "why", "check", "severity")}
            risk["properties"]["evidence_id"] = {"type": "string", "enum": list(self._evidence)}
            risk["additionalProperties"] = False
            schema["properties"]["risks"]["maxItems"] = 3
            schema["properties"]["specs"]["maxItems"] = 3
            schema["additionalProperties"] = False
            getattr(self._complete, "set_schema", lambda _: None)(schema)
        return "\n".join(blocks)

    def _resolve_evidence(self, reply: str) -> str:
        from app.packauthor import _payload
        found = _payload(reply)
        if not isinstance(found, dict):
            from app.quicklook import closed
            found = closed(reply)
        if not isinstance(found, dict):
            self.telemetry["last_reply"] = reply[-4000:]
            return reply
        for risk in found.get("risks") or []:
            if not isinstance(risk, dict):
                continue
            evidence_id = str(risk.get("evidence_id") or "").strip()
            if evidence_id:
                url, quote = getattr(self, "_evidence", {}).get(evidence_id, ("", ""))
                risk["url"], risk["quote"] = url, quote
        return json.dumps(found, ensure_ascii=False)

    def _reply_budget(self) -> str:
        """The reply's length limit, said to the model.

        A CPU writes a few tokens a second, and a reply cut off at
        `max_tokens` is minutes spent on JSON that does not close. Measured
        on a 3B model on four cores: 1 024 tokens took 145 s and parsed to
        nothing. Told the limit, the model writes fewer items and finishes
        them.
        """
        limit = getattr(self._complete, "max_tokens", None)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            return ""
        return (f"\n\n## Length\n\nYour whole reply must fit in about "
                f"{int(limit * 0.6)} words. Keep every field short and give "
                "fewer items rather than more: a finished reply with two items "
                "beats a longer one that is cut off before it closes.\n")

    def _fit(self, prompt: str, pages: list[tuple[str, str]],
             queries: list[str]) -> list[tuple[str, str]]:
        """The pages, cut to fit the context the server runs the model with.

        A local server cuts a prompt that overflows its window from the
        front, silently, and the front is the instructions: a run measured
        on Ollama's default 4k window kept 2 050 of 4 331 tokens and
        answered with nothing. So the pages share what the brief leaves,
        fewer of them when the share would be a fragment, and `sources`
        holds exactly what was shown, because that is what quotes are
        checked against.
        """
        allowed = getattr(self._complete, "prompt_chars_allowed", None)
        if not callable(allowed):
            # No window to fit: each page is still cut to `PAGE_CHARS` around
            # the queries, and the cut text is what the quotes are checked on.
            fitted = [(url, focus(text, PAGE_CHARS, queries)) for url, text in pages]
            self.sources = dict(fitted)
            return fitted
        task = len(prompt) + len(_PAGES_HEAD) + len(self._reply_budget()) + 500
        whole = getattr(self._complete, "window_chars", None)
        # The window bounds instructions plus evidence; the research budget
        # bounds the evidence alone. Charging the instructions to the research
        # budget left an authoring brief no room on any window (#181).
        room = (min(allowed(), whole() - task) if callable(whole)
                else allowed() - task)
        count = len(pages)
        while count > 1 and room // count < MIN_SHARE:
            count -= 1
        if room < 200:
            window = getattr(self._complete, "context_tokens", lambda: 0)()
            holds = whole() if callable(whole) else allowed()
            raise LocalInferenceError(
                f"The instructions for this task take {task} characters and "
                f"this model's {window}-token window holds about {holds} beside "
                "its reply, which leaves no room for evidence. Serve the model "
                "with a larger context window (Settings, Local machine).",
                code="context_limit")
        share = max(1, room // max(1, count) - max(len(url) + 20 for url, _ in pages[:count]))
        fitted = [(url, focus(text, share, queries)) for url, text in pages[:count]]
        if count < len(pages) or any(len(a) < len(b) for (_, a), (_, b) in zip(fitted, pages)):
            window = getattr(self._complete, "context_tokens", lambda: 0)()
            self._say(f"fitted {count} of {len(pages)} page(s) into the model's "
                      f"{window}-token context")
        self.sources = dict(fitted)
        return fitted

    def _queries(self, prompt: str) -> list[str]:
        # A case may name its own queries (B185): the fixed set's queries
        # are part of its versioned ground truth, and letting the model
        # invent its own would quietly change what the run measured.
        if self.given_queries:
            return list(self.given_queries)[:QUERIES]
        if self.identity:
            # A quick check already has its exact subject. Avoid a separate
            # CPU inference just to restate that subject as search queries.
            # The angles are how a buyer words the question, so each one lands
            # on a different kind of page: reports, reviews, forums, repairs.
            # A local scraper takes one query at a time, so it gets fewer.
            angles = QUICK_ANGLES if self.parallel_search else QUICK_ANGLES[:3]
            return [f"{self.identity} {angle}" for angle in angles]
        task = prompt[:PLAN_CHARS]
        queries = self._usable(self._plan(_QUERY_ASK.format(n=QUERIES, task=task)))
        if not queries:
            # One repair, said plainly: a small model that answered with a
            # url or prose once usually answers the plain ask right.
            self._say("the planner's reply held no usable query; asking once more")
            queries = self._usable(self._plan(_QUERY_RETRY.format(n=QUERIES, task=task)))
        if not queries:
            raise LocalInferenceError(
                f"{self.model!r} at {self.url or 'this machine'} did not "
                "propose any search query, so nothing was searched. A larger "
                "model follows this kind of instruction more reliably.")
        if self.identity:
            identity = set(re.findall(r"\w+", self.identity.casefold()))
            queries = [query if len(identity & set(re.findall(r"\w+", query.casefold()))) >= max(2, len(identity) // 2)
                       else f"{self.identity} {query}" for query in queries]
        return queries

    @staticmethod
    def _usable(raw: str) -> list[str]:
        """The search queries in a planner's reply: no urls, no sentences,
        no repeats, at most `QUERIES`."""
        try:
            found = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
        except ValueError:
            found = []
        if not isinstance(found, list):
            found = []
        queries: list[str] = []
        lowered: set[str] = set()
        for one in found:
            text = str(one).strip()
            low = text.casefold()
            if (not text or low in lowered or "://" in text or low.startswith("www.")
                    or len(text.split()) > QUERY_WORDS):
                continue
            lowered.add(low)
            queries.append(text)
            if len(queries) >= QUERIES:
                break
        return queries

    def _read(self, queries: list[str], *, identity=None,
              prefer_issues: bool = False,
              quick: bool = False) -> list[tuple[str, str]]:
        """Prefer issue discussions and replace unreadable/unrelated pages."""
        from app.providers.local_pipeline import canonical_url, publisher, repair_offer_page
        from app.providers.local_identity import relevant_source, source_scope
        import hashlib

        self.search_coverage = {"queries_searched": 0, "search_errors": 0,
                                "unique_hits": 0, "pages_unreadable": 0,
                                "pages_read": 0, "pages_irrelevant": 0,
                                "pages_duplicate": 0, "pages_selected": 0,
                                "pages_service_offers": 0,
                                "publishers_read": 0, "pages_timed_out": 0}
        self.relevant_sources = {}
        if self.given_sources is not None:
            self.sources = dict(self.given_sources)
            self.relevant_sources = dict(self.sources)
            return list(self.sources.items())
        limit = 10 if prefer_issues else HITS_PER_QUERY
        gather_started = time.monotonic()
        gather_deadline = (gather_started + QUICK_READ_DEADLINE
                           if quick else None)
        read_stop = threading.Event()
        timed_out_reads: set[str] = set()
        timed_out_lock = threading.Lock()
        # Per-page scrape cost. The reads run in a pool, so the only honest
        # place to time one is inside the worker that owns it — a whole-phase
        # figure hides the one host that took twenty seconds and held the run.
        fetch_facts: dict[str, dict] = {}
        fetch_lock = threading.Lock()

        def worker_read_check(url: str = "") -> None:
            # The job thread owns cancellation checks; fetch workers only see
            # this event and the monotonic gathering deadline. This check is
            # also passed into the fetch ladder so a refused page cannot
            # launch hosted-reader or browser fallbacks after the run stops.
            if read_stop.is_set():
                from app.providers.fetch import FetchCancelled
                raise FetchCancelled("page read cancelled")
            if gather_deadline is not None and time.monotonic() >= gather_deadline:
                read_stop.set()
                if url:
                    with timed_out_lock:
                        timed_out_reads.add(url)
                from app.providers.fetch import FetchCancelled
                raise FetchCancelled("page reading budget reached")

        def read_one(url: str) -> tuple[str, str]:
            started = time.perf_counter()
            text = ""
            reason = ""
            try:
                options: dict[str, object] = {}
                if getattr(self._fetch, "supports_cancel_check", False):
                    options["check_cancelled"] = lambda: worker_read_check(url)
                if getattr(self._fetch, "supports_timeout", False):
                    if gather_deadline is not None:
                        remaining = gather_deadline - time.monotonic()
                        if remaining <= 0:
                            worker_read_check(url)
                        options["timeout"] = remaining
                if getattr(self._fetch, "supports_fallback", False) and quick:
                    # Quick Look is a bounded evidence pass. The plain fetch
                    # gets its remaining budget; a 403 must not start two
                    # more remote requests (or a browser process) after it.
                    # Measured with the ladder enabled anyway: three pages
                    # read instead of one on a forum-heavy product, and 51 s
                    # instead of 23, for the same zero kept claims — the extra
                    # pages did not survive extraction either. Latency was the
                    # only thing that changed, so the ladder stays off here.
                    options["allow_fallback"] = False
                worker_read_check(url)
                got = self._fetch(url, **options)
                text = str(getattr(got, "text", got) or "").strip()
                return url, text[:24000] if len(text) >= MIN_PAGE_CHARS else ""
            except Exception as error:  # noqa: BLE001 - fetch is a network boundary
                # The reason is kept, not just the miss: "8 of 9 pages failed"
                # is only actionable if the page says 403, a timeout or a bot
                # wall, and the console shows it per page.
                reason = f"{type(error).__name__}: {error}"[:180]
                return url, ""
            finally:
                with fetch_lock:
                    fetch_facts[url] = {
                        "ms": round((time.perf_counter() - started) * 1000, 3),
                        "characters": len(text),
                        "error": reason,
                    }

        search_deadline = (gather_started + min(QUICK_SEARCH_DEADLINE,
                                                 QUICK_READ_DEADLINE)
                           if quick else None)
        engines = tuple(dict.fromkeys(str(name) for name in
                        getattr(self._search, "engines", None) or ()))
        engine_locks = {name: threading.Lock() for name in engines}
        engine_parallel = len(engines) > 1 and not self.parallel_search

        def answer(query: str, index: int = 0, engine: str = "") -> tuple[list, str]:
            try:
                options: dict[str, float | str] = {}
                if quick and getattr(self._search, "supports_timeout", False):
                    remaining = (search_deadline - time.monotonic()
                                 if search_deadline is not None else QUICK_SEARCH_TIMEOUT)
                    if remaining <= 0:
                        return [], "quick-look search budget reached"
                    options["timeout"] = min(QUICK_SEARCH_TIMEOUT, remaining)
                    if getattr(self._search, "supports_pacing", False):
                        options["pace_interval"] = QUICK_SEARCH_PACE_INTERVAL
                    if getattr(self._search, "supports_fast_options", False):
                        options["mode"] = "any"
                        if engines:
                            offset = index % len(engines)
                            options["engines"] = ",".join(engines[offset:] + engines[:offset])
                if engine:
                    options["engines"] = engine
                    lock = engine_locks[engine]
                    while not lock.acquire(timeout=0.05):
                        worker_check()
                        if search_deadline is not None and time.monotonic() >= search_deadline:
                            return [], "quick-look search budget reached"
                    try:
                        worker_check()
                        return self._search(query, limit, **options) or [], ""
                    finally:
                        lock.release()
                return self._search(query, limit, **options) or [], ""
            except LocalSearchError as error:
                return [], str(error)

        # Said before the wait, not after it: a search can take half a minute,
        # and a screen that shows nothing meanwhile reads as a hang.
        for query in queries:
            self._say(f"searching: {query}")

        # In a Quick Look, page reads start as soon as the first query has
        # results, alongside the remaining searches. A slow secondary query
        # therefore does not hold the first useful page behind it.
        prefetch_pool = ThreadPoolExecutor(max_workers=4 + HEDGED_PAGES) if quick else None
        prefetch_futures: dict[str, Future] = {}
        prefetch_announced: set[Future] = set()
        prefetch_seen: set[str] = set()
        prefetch_per_query: dict[int, int] = {}
        prefetch_results: list[tuple[list, str] | None] = [None] * len(queries)

        def prefetch_ready() -> None:
            if prefetch_pool is None:
                return
            # Use a fast secondary result while an earlier query is still
            # running, but reserve three candidates for query zero. Once the
            # first query answers (or times out), any unused slots are shared.
            for index, result in enumerate(prefetch_results):
                if result is None:
                    continue
                hits, _failure = result
                budget = self.max_pages + SPARE_PAGES
                quota = min(3, budget) if index == 0 else (
                    budget if prefetch_results[0] is not None else 2)
                for hit in hits:
                    if prefetch_per_query.get(index, 0) >= quota:
                        break
                    if not isinstance(hit, dict):
                        continue
                    url = canonical_url(str(hit.get("url", "")))
                    if not url or url in prefetch_seen:
                        continue
                    if len(prefetch_futures) >= self.max_pages + SPARE_PAGES:
                        break
                    prefetch_seen.add(url)
                    self.page_titles[url] = str(hit.get("title") or "")[:240]
                    prefetch_per_query[index] = prefetch_per_query.get(index, 0) + 1
                    prefetch_futures[url] = prefetch_pool.submit(read_one, url)

        # On a hosted search the queries go out together; their hits are
        # still taken in the queries' order, and the log is written from
        # this thread only.
        has_search_check = hasattr(self._search, "check_cancelled")
        prior_search_check = getattr(self._search, "check_cancelled", None)
        search_stop = threading.Event()

        def worker_check() -> None:
            # Progress.check may read SQLite through a connection owned by the
            # job thread. Search workers use only this thread-safe signal; the
            # job thread sets it when its own cancellation check fires.
            if search_stop.is_set():
                raise LocalSearchError("search cancelled")

        concurrent_search = ((self.parallel_search or quick or engine_parallel)
                             and len(queries) > 1)
        if has_search_check:
            self._search.check_cancelled = (
                worker_check if concurrent_search
                else self._check
            )
        if concurrent_search:
            # Independent public engines can answer together. Each engine has
            # its own lock, so another query cannot overlap it; hosted search
            # sockets retain their existing parallel path.
            workers = (min(len(queries), QUERIES) if self.parallel_search else
                       min(len(queries), len(engines)) if engine_parallel else 1)
            pool = ThreadPoolExecutor(max_workers=workers)
            search_futures = {pool.submit(answer, query, index,
                                         engines[index % len(engines)] if engine_parallel else ""): index
                               for index, query in enumerate(queries)}
            search_pending = set(search_futures)
            ordered: list[tuple[list, str] | None] = [None] * len(queries)
            stopped = False
            try:
                while search_pending:
                    try:
                        self._check()
                    except BaseException:
                        stopped = True
                        search_stop.set()
                        read_stop.set()
                        raise
                    search_done, not_done = wait(
                        search_pending, timeout=(min(0.05, max(0.0, search_deadline - time.monotonic()))
                                          if search_deadline is not None else 0.05),
                        return_when=FIRST_COMPLETED)
                    search_pending = not_done
                    for search_future in search_done:
                        index = search_futures[search_future]
                        result = search_future.result()
                        ordered[index] = result
                        prefetch_results[index] = result
                        prefetch_ready()
                        hits, failure = result
                        if failure:
                            self._say(f"search failed for {queries[index]!r}: {failure}")
                        else:
                            self._say(
                                f"search returned {len(hits)} result(s) for {queries[index]!r}")
                    if quick:
                        for url, prefetch_future in prefetch_futures.items():
                            if prefetch_future.done() and prefetch_future not in prefetch_announced:
                                prefetch_announced.add(prefetch_future)
                                self._say(f"page fetched; checking product match: {url}")
                    if search_pending and search_deadline is not None and time.monotonic() >= search_deadline:
                        stopped = True
                        search_stop.set()
                        for search_future in tuple(search_pending):
                            index = search_futures[search_future]
                            ordered[index] = ([], "quick-look search budget reached")
                            prefetch_results[index] = ordered[index]
                        search_pending.clear()
                        prefetch_ready()
                        self._say("quick-look search budget reached; keeping completed results")
                if engine_parallel and not stopped and not all(
                        result is not None and result[1] for result in ordered):
                    # Retry empty angles across the configured engines only
                    # after the independent first pass has finished. A dead
                    # service is never retried query by query.
                    if has_search_check:
                        self._search.check_cancelled = self._check
                    for index, initial_result in enumerate(ordered):
                        if initial_result is None or initial_result[0]:
                            continue
                        self._check()
                        ordered[index] = answer(queries[index], index)
                        prefetch_results[index] = ordered[index]
                        prefetch_ready()
            except BaseException:
                stopped = True
                search_stop.set()
                read_stop.set()
                if prefetch_pool is not None:
                    prefetch_pool.shutdown(wait=False, cancel_futures=True)
                raise
            finally:
                if has_search_check:
                    unfinished = {search_future for search_future in search_futures
                                  if not search_future.done()}
                    if stopped and unfinished:
                        # Keep the event-backed callback installed until an
                        # abandoned worker has left the search function. It
                        # may still poll the callback while unwinding after the
                        # job has returned from cancellation.
                        restore_lock = threading.Lock()

                        def restore_after(search_future):
                            def finished(_completed):
                                with restore_lock:
                                    unfinished.discard(search_future)
                                    if not unfinished:
                                        self._search.check_cancelled = prior_search_check
                            return finished

                        for search_future in tuple(unfinished):
                            search_future.add_done_callback(restore_after(search_future))
                    else:
                        self._search.check_cancelled = prior_search_check
                # A canceled run must return without joining a slow network
                # request. The workers see search_stop while waiting for a
                # host permit; active sockets retain their own finite timeout.
                pool.shutdown(wait=not stopped, cancel_futures=stopped)
            answered = [one for one in ordered if one is not None]
        else:
            try:
                answered = []
                for query in queries:
                    self._check()
                    if len(answered) >= 2 and all(failure for _, failure in answered):
                        # Two searches in a row failed outright: a service that is
                        # down answers the third no better, and each one waits out
                        # its own timeout first (measured: 127 s of silence).
                        answered.append(([], "skipped, the search service is not answering"))
                        continue
                    answered.append(answer(query, len(answered)))
            except BaseException:
                read_stop.set()
                if prefetch_pool is not None:
                    prefetch_pool.shutdown(wait=False, cancel_futures=True)
                raise
            finally:
                if has_search_check:
                    self._search.check_cancelled = prior_search_check
            for index, result in enumerate(answered):
                prefetch_results[index] = result
            prefetch_ready()
        hits_by_query = []
        for query, (hits, failure) in zip(queries, answered):
            if failure:
                if not concurrent_search:
                    self._say(f"search failed for {query!r}: {failure}")
                self.search_coverage["search_errors"] += 1
                continue
            self.search_coverage["queries_searched"] += 1
            hits_by_query.append(hits)
        wanted, seen = [], set()
        # A query cannot fill the entire source set before the next query runs.
        for rank in range(10 if prefer_issues else HITS_PER_QUERY):
            for hits in hits_by_query:
                if rank >= len(hits) or not isinstance(hits[rank], dict):
                    continue
                url = canonical_url(str(hits[rank].get("url", "")))
                if url and url not in seen:
                    seen.add(url)
                    self.page_titles[url] = str(hits[rank].get("title") or "")[:240]
                    wanted.append(url)
        self.search_coverage["unique_hits"] = len(wanted)
        # The search is done once every query has settled; page reads that
        # started during it are timed separately, per page, below.
        self._phase("search", gather_started, queries=len(queries), hits=len(wanted))
        def issue_priority(url: str) -> int:
            if _is_index_page(url):
                # A door is not a page: it would take an evidence pass and
                # return thread titles.
                return -1
            label = (url + " " + self.page_titles.get(url, "")).casefold()
            if re.search(r"\b(?:forums?|threads?|communities|community|discussion|discuss|"
                         r"boards?|subreddit)\b|/r/|/comments/|/t/", label):
                return 3
            if re.search(r"\b(?:manuals?|technical data|technical document(?:ation)?|"
                         r"specifications?|datasheets?|product support|service bulletins?|"
                         r"recalls?|fiche technique|manuel|données techniques|"
                         r"technische daten|handbuch|ficha técnica|manual de usuario|"
                         r"teknik özellikler|kullanım kılavuzu)\b|/manual|/support|/datasheet", label):
                return 3
            if re.search(r"\b(?:problems?|issues?|failures?|broken|defects?|repair|"
                         r"troubleshoot\w*|pannes?|problèmes?|défauts?|réparation|"
                         r"sorun\w*|arıza\w*|tamir|fehler|defekt\w*)\b", label):
                return 2
            if re.search(r"\b(?:review|test|avis|long.term)\b", label):
                return 1
            if re.search(r"\b(?:buy|shop|price|specifications|specs|manuals|"
                         r"acheter|prix|fiche|caractéristiques)\b|/products?/|/dp/", label):
                return -1
            return 0

        def title_relevance(url: str) -> tuple[int, int]:
            """Rank result titles by the supplied identity, without guessing a category."""
            if identity is None:
                return (0, 0)
            from app.providers.local_identity import anchor_terms, fold

            title = self.page_titles.get(url, "") + " " + url
            folded = fold(title)
            terms = anchor_terms(identity)
            exact = sum(bool(term and fold(term) in folded) for term in terms)
            tokens = {token for term in terms for token in re.findall(r"[^\W_]+", fold(term))
                      if len(token) >= 4}
            overlap = len(tokens & set(re.findall(r"[^\W_]+", folded)))
            return exact, overlap

        if prefer_issues:
            wanted.sort(key=lambda url: (title_relevance(url), issue_priority(url)), reverse=True)
        domains: set[str] = set()
        diverse: list[str] = []
        repeated: list[str] = []
        prioritized: list[str] = []
        # Diversity within each priority level: a low-value catalog must not
        # jump ahead of another useful discussion merely to add a publisher.
        for priority in (3, 2, 1, 0, -1) if prefer_issues else (0,):
            diverse, repeated = [], []
            for url in wanted:
                if prefer_issues and issue_priority(url) != priority:
                    continue
                domain = publisher(url)
                if domain in domains:
                    repeated.append(url)
                else:
                    domains.add(domain)
                    diverse.append(url)
            prioritized.extend(diverse + repeated)
        # Only a few replacement candidates are useful: a long tail of weak
        # search hits made unrelated video/shop pages spend the whole fetch
        # deadline before a usable report or product document was reached.
        wanted = prioritized[:self.max_pages + SPARE_PAGES]
        self._say(f"found {len(seen)} page(s); reading up to {self.max_pages}")

        pages: list[tuple[str, str]] = []
        fingerprints, read_domains = set(), set()
        processed_urls: set[str] = set()
        queue = iter(wanted)
        deadline = (gather_deadline if gather_deadline is not None
                    else time.monotonic() + READ_DEADLINE)
        pool = prefetch_pool or ThreadPoolExecutor(max_workers=4 + HEDGED_PAGES)
        read_pending: dict[Future, str] = {}
        hedge = False
        last_progress = time.monotonic()
        def fill() -> None:
            while len(read_pending) < (4 + HEDGED_PAGES if hedge else
                                      min(4, self.max_pages - len(pages))):
                url = next(queue, None)
                if url is None:
                    break
                prefetch_future = prefetch_futures.get(url)
                read_pending[prefetch_future or pool.submit(read_one, url)] = url
        try:
            fill()
            while read_pending and len(pages) < self.max_pages:
                self._check()
                if not hedge and time.monotonic() - last_progress >= HEDGE_AFTER:
                    hedge = True
                    self._say("slow pages; reading spares beside them")
                    fill()
                left = deadline - time.monotonic()
                if left <= 0:
                    read_done = {read_future for read_future in read_pending
                                 if read_future.done()}
                    if not read_done:
                        break
                else:
                    read_done, _ = wait(read_pending, timeout=min(1.0, left),
                                        return_when=FIRST_COMPLETED)
                if read_done:
                    last_progress = time.monotonic()
                for read_future in sorted(
                        read_done, key=lambda item: wanted.index(read_pending[item])):
                    read_pending.pop(read_future)
                    url, page_text = read_future.result()
                    processed_urls.add(url)
                    if not page_text:
                        with timed_out_lock:
                            timed_out = url in timed_out_reads
                        if timed_out:
                            self.search_coverage["pages_timed_out"] += 1
                            self._say(f"page read budget reached: {url}")
                        else:
                            self.search_coverage["pages_unreadable"] += 1
                            self._say(f"could not read: {url}")
                        continue
                    self.search_coverage["pages_read"] += 1
                    read_domains.add(publisher(url))
                    if identity is not None and not relevant_source(
                            identity, self.page_titles.get(url, ""), page_text):
                        self.search_coverage["pages_irrelevant"] += 1
                        scope = source_scope(identity, self.page_titles.get(url, ""), page_text)
                        if scope == "host_only":
                            self.search_coverage["pages_host_only"] = (
                                self.search_coverage.get("pages_host_only", 0) + 1)
                            self._say("replacing page about the product it fits, "
                                      f"not the part itself: {url}")
                        else:
                            self._say(f"replacing page without an exact product match: {url}")
                        continue
                    fingerprint = hashlib.sha256(" ".join(page_text.casefold().split()).encode()).hexdigest()
                    if prefer_issues and repair_offer_page(url, self.page_titles.get(url, ""), page_text):
                        self.search_coverage["pages_service_offers"] += 1
                        self._say(f"replacing repair-service advertisement, not an incident report: {url}")
                        continue
                    if fingerprint in fingerprints:
                        self.search_coverage["pages_duplicate"] += 1
                        self._say(f"replacing copied page: {url}")
                        continue
                    fingerprints.add(fingerprint)
                    pages.append((url, page_text))
                    self.sources[url] = page_text
                    self._say(f"read: {url}")
                fill()
            if read_pending and time.monotonic() >= deadline:
                if quick:
                    self.search_coverage["pages_timed_out"] = len(set(wanted) - processed_urls)
                else:
                    self.search_coverage["pages_timed_out"] = len(read_pending)
                self._say(f"page reading deadline reached; {self.search_coverage['pages_timed_out']} page(s) still waiting")
        except BaseException:
            read_stop.set()
            raise
        finally:
            read_stop.set()
            pool.shutdown(wait=False, cancel_futures=True)
        self.search_coverage["pages_selected"] = len(pages)
        self.search_coverage["publishers_read"] = len(read_domains)
        kept = {url for url, _text in pages}
        for url in wanted:
            facts = fetch_facts.get(url)
            if facts is None:
                continue
            missed = url not in kept
            self._record({"stage": "fetch", "ms": facts["ms"],
                          "failed": missed, "url": url,
                          "characters": facts["characters"],
                          **({"error": facts.get("error") or "no readable text"}
                             if missed else {})})
        # The page-level half of the decision dataset: what was attempted,
        # what came back, and whether it was kept. It is the training and
        # scoring material for any page-worthiness rule or model later.
        self.search_coverage["page_outcomes"] = [
            {"url": url, "ms": facts["ms"],
             "characters": facts["characters"], "kept": url in kept,
             "error": (facts.get("error") or "")[:120]}
            for url, facts in list(fetch_facts.items())[:40]]
        self.relevant_sources = dict(self.sources)
        self._say(f"read {self.search_coverage['pages_read']} page(s) from "
                  f"{len(read_domains)} publisher buckets; selected {len(pages)} usable product pages")
        return pages


class _MeasuredSocket:
    """Keep the socket API intact while accounting for each actual call."""
    def __init__(self, socket, owner, stage):
        object.__setattr__(self, "socket", socket)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "stage", stage)

    def __getattr__(self, name):
        return getattr(self.socket, name)

    def __setattr__(self, name, value):
        setattr(self.socket, name, value)

    def _invoke(self, call):
        return self._invoke_for(self._stage(), call)

    def _stage(self) -> str:
        """The stage this call belongs to.

        The socket does not know what it is being asked for; the caller does.
        `local_pipeline.QuickLookPipeline` sets `owner._stage_hint` around each
        structured call, so one quick look reports `identity`, `extract`,
        `verify` and `render` separately instead of twenty rows called
        "answer" — which is what the operator console had to show before.
        """
        return getattr(self.owner, "_stage_hint", "") or self.stage

    def json(self, prompt, schema):
        """The structured reply, or, from a plain socket that has no schema, the text."""
        if not callable(getattr(self.socket, "json", None)):
            return self(prompt)
        return self._invoke(lambda: self.socket.json(prompt, schema))

    def stream(self, prompt, on_text):
        """The reply as it is written, or, from a socket that cannot stream, whole."""
        if not callable(getattr(self.socket, "stream", None)):
            text = self(prompt)
            on_text(text)
            return text
        return self._invoke(lambda: self.socket.stream(prompt, on_text))

    def __call__(self, prompt):
        hint = getattr(self.owner, "_stage_hint", "")
        stage = hint or ("verify" if prompt.startswith("Check evidence for ") else self.stage)
        return self._invoke_for(stage, lambda: self.socket(prompt))

    def _invoke_for(self, stage, call):
        setter = getattr(self.socket, "set_cancel_check", None)
        if not callable(setter):
            return self.owner._measured(stage, self.socket, call)
        previous = getattr(self.socket, "check_cancelled", None)
        setter(self.owner._check if self.owner.check_cancelled is not None else None)
        try:
            return self.owner._measured(stage, self.socket, call)
        finally:
            setter(previous)
