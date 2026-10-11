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
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

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
#: Candidate pages asked for beyond `MAX_PAGES`, so a page that is slow or
#: unreadable is replaced by the next one instead of leaving a gap.
SPARE_PAGES = 3
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
        try:
            return call()
        except Exception:
            failed = True
            raise
        finally:
            row = {"stage": stage, "ms": round(
                (time.perf_counter() - started) * 1000, 3), "failed": failed}
            for key, value in before.items():
                now = getattr(socket, key, None)
                row[key] = (now - (value or 0) if getattr(socket, "last_usage_complete", True)
                            and isinstance(now, int)
                            and not isinstance(now, bool) else None)
            self.metrics.append(row)

    def _say(self, line: str) -> None:
        self.telemetry["stages"].append({"elapsed_ms": int((time.monotonic() - getattr(self, "_started", time.monotonic())) * 1000), "message": line})
        if self.on_action is not None:
            self.on_action(line)

    def _check(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()

    def ask(self, prompt: str) -> str:
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
            self.telemetry.update(coverage=self.coverage, identity=self.identity,
                                  stages=self.metrics)

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
            return pages
        room = allowed() - len(prompt) - len(_PAGES_HEAD) - len(self._reply_budget()) - 500
        count = len(pages)
        while count > 1 and room // count < MIN_SHARE:
            count -= 1
        if room < 200:
            raise LocalInferenceError("The task leaves no room for evidence in this model's context. Increase the context window or shorten the task.", code="context_limit")
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
              prefer_issues: bool = False) -> list[tuple[str, str]]:
        """Prefer issue discussions and replace unreadable/unrelated pages."""
        from app.providers.local_pipeline import canonical_url, publisher, repair_offer_page
        from app.providers.local_identity import relevant_source
        import hashlib

        self.search_coverage = {"queries_searched": 0, "search_errors": 0,
                                "unique_hits": 0, "pages_unreadable": 0,
                                "pages_read": 0, "pages_irrelevant": 0,
                                "pages_duplicate": 0, "pages_selected": 0,
                                "pages_service_offers": 0,
                                "publishers_read": 0, "pages_timed_out": 0}
        if self.given_sources is not None:
            self.sources = dict(self.given_sources)
            return list(self.sources.items())
        hits_by_query = []
        for query in queries:
            self._check()
            try:
                hits = self._search(query, 10 if prefer_issues else HITS_PER_QUERY) or []
                self.search_coverage["queries_searched"] += 1
            except LocalSearchError as error:
                self._say(f"search failed for {query!r}: {error}")
                self.search_coverage["search_errors"] += 1
                continue
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
        def issue_priority(url: str) -> int:
            label = (url + " " + self.page_titles.get(url, "")).casefold()
            if re.search(r"\b(?:forums?|threads?|communities|community|discussion|discuss|"
                         r"boards?|subreddit)\b|/r/|/comments/|/t/", label):
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

        if prefer_issues:
            wanted.sort(key=issue_priority, reverse=True)
        domains, diverse, repeated = set(), [], []
        prioritized = []
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
        wanted = prioritized[:max(24, min(150, self.max_pages * 5))]

        def read_one(url: str) -> tuple[str, str]:
            try:
                got = self._fetch(url)
            except Exception:  # noqa: BLE001 - fetch is a network boundary
                return url, ""
            text = str(getattr(got, "text", got) or "").strip()
            return url, text[:24000] if len(text) >= MIN_PAGE_CHARS else ""

        pages: list[tuple[str, str]] = []
        fingerprints, read_domains = set(), set()
        queue = iter(wanted)
        deadline = time.monotonic() + (40.0 if prefer_issues else READ_DEADLINE)
        pool = ThreadPoolExecutor(max_workers=4)
        pending = {}
        def fill() -> None:
            while len(pending) < min(4, self.max_pages - len(pages)):
                url = next(queue, None)
                if url is None:
                    break
                pending[pool.submit(read_one, url)] = url
        try:
            fill()
            while pending and len(pages) < self.max_pages and time.monotonic() < deadline:
                self._check()
                done, _ = wait(pending, timeout=min(1.0, max(0.0, deadline - time.monotonic())),
                               return_when=FIRST_COMPLETED)
                for future in sorted(done, key=lambda item: wanted.index(pending[item])):
                    pending.pop(future)
                    url, text = future.result()
                    if not text:
                        self.search_coverage["pages_unreadable"] += 1
                        continue
                    self.search_coverage["pages_read"] += 1
                    read_domains.add(publisher(url))
                    if identity is not None and not relevant_source(
                            identity, self.page_titles.get(url, ""), text):
                        self.search_coverage["pages_irrelevant"] += 1
                        self._say(f"replacing page without an exact product match: {url}")
                        continue
                    fingerprint = hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()
                    if prefer_issues and repair_offer_page(url, self.page_titles.get(url, ""), text):
                        self.search_coverage["pages_service_offers"] += 1
                        self._say(f"replacing repair-service advertisement, not an incident report: {url}")
                        continue
                    if fingerprint in fingerprints:
                        self.search_coverage["pages_duplicate"] += 1
                        self._say(f"replacing copied page: {url}")
                        continue
                    fingerprints.add(fingerprint)
                    pages.append((url, text))
                    self.sources[url] = text
                fill()
            if pending and time.monotonic() >= deadline:
                self.search_coverage["pages_timed_out"] = len(pending)
                self._say(f"page reading deadline reached; {len(pending)} page(s) still waiting")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        self.search_coverage["pages_selected"] = len(pages)
        self.search_coverage["publishers_read"] = len(read_domains)
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

    def json(self, prompt, schema):
        return self.owner._measured(self.stage, self.socket,
                                   lambda: self.socket.json(prompt, schema))

    def stream(self, prompt, on_text):
        """The reply as it is written, or, from a socket that cannot stream, whole."""
        if not callable(getattr(self.socket, "stream", None)):
            text = self(prompt)
            on_text(text)
            return text
        return self.owner._measured(self.stage, self.socket,
                                   lambda: self.socket.stream(prompt, on_text))

    def __call__(self, prompt):
        stage = "verify" if prompt.startswith("Check evidence for ") else self.stage
        return self.owner._measured(stage, self.socket, lambda: self.socket(prompt))
