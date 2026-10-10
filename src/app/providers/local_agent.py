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
REPLY_MAX_TOKENS = 1024

from kriko.research.politeness import LocalSearchError
from kriko.research.window import focus

#: Queries proposed, hits taken per query and pages read in all. Small on
#: purpose: each page costs a model call's worth of context on a CPU.
QUERIES = 3
HITS_PER_QUERY = 3
MAX_PAGES = 5
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
                 requested_specs: list[str] | None = None):
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
        if self.given_sources is not None or prompt.startswith("# Quick look:"):
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
        return self._complete(prompt + _PAGES_HEAD + blocks + self._reply_budget())

    def ask_quick(self, product: str, *, principle: str = "", page: dict | None = None,
                  packs: str = "", attributes: str = "") -> str:
        """A compact, bounded local answer with one repair and saved verification.

        Generic pack authoring keeps its full brief. The quick door reserves
        context for evidence instead of repeating a long chat-style brief.
        The source gate runs after every repair; a model cannot validate itself.
        """
        from app import pagefacts, quicklook
        from app.packauthor import _payload
        set_schema = getattr(self._complete, "set_schema", lambda _schema: None)
        set_schema(QUICK_SCHEMA)
        self.identity = product
        brief = (
            f"Research this exact product: {product}\n{pagefacts.block(page)[:1000]}\n"
            "Answer ONLY one JSON object with assumed, category, pack, specs, risks. "
            "specs: [{name,value,url}]. risks: [{title,why,check,severity,evidence_id}]. "
            "At most 3 risks. Cite evidence_id (such as E1) from a provided passage. "
            "Keep titles under 8 words; why and check each one complete sentence under 20 words. "
            "Never translate or reconstruct a quote. A passage about a different product "
            "or a general feature cannot support a fault in this product. "
            "Use empty arrays when evidence supports nothing. Do not invent sources.\n"
            + identity.GUIDANCE + self.source_instructions + "\n"
            + (f"Worth saying: {principle[:1200]}\n" if principle else "")
            + (f"Installed packs: {packs[:500]}\n" if packs else "")
            + (f"Specification names: {attributes[:300]}\n" if attributes else ""))
        reply = self._resolve_evidence(self.ask(brief))
        raw = _payload(reply)
        parsed = quicklook.parse(reply, self.sources)
        if (isinstance(raw, dict) and isinstance(raw.get("risks"), list)
                and not parsed["risks"] and not parsed["specs"] and not self.given_queries):
            self._check()
            observations = "\n".join(f"{url}: {text[:350]}" for url, text in list(self.sources.items())[:2])
            learned = self._usable(self._plan(
                f"Find more specific evidence for this exact product: {product}. "
                "Reply ONLY a JSON array of one new web query. Learn from these "
                f"pages already read; do not repeat {self.telemetry['queries']}.\n{observations}"))
            learned = [q for q in learned if q.casefold() not in {x.casefold() for x in self.telemetry["queries"]}][:1]
            if learned:
                self._say("refining search from the first pages: " + learned[0])
                self.telemetry["queries"].extend(learned)
                more = self._read(learned)
                combined = list(dict([*self.sources.items(), *more]).items())[:self.max_pages]
                fitted = self._fit(brief, combined, self.telemetry["queries"])
                blocks = self._blocks(fitted)
                reply = self._resolve_evidence(self._complete(brief + _PAGES_HEAD + blocks + self._reply_budget()))
                raw = _payload(reply)
                parsed = quicklook.parse(reply, self.sources)
        needs_repair = not isinstance(raw, dict) or not isinstance(raw.get("risks"), list)
        if needs_repair or parsed["dropped"]:
            self._check()
            self._say("repairing the answer once: valid JSON and quotes from read pages only")
            self.telemetry["repairs"] += 1
            repair = brief + "\nRepair the previous answer; keep supported facts only.\n"
            # Refit with the repair instructions and the previous reply in the
            # budget. The gate still sees exactly the pages the socket saw.
            previous = "\nPrevious answer:\n" + reply[:1200]
            fitted = self._fit(repair + previous, list(self.sources.items()), self.telemetry["queries"])
            blocks = self._blocks(fitted)
            reply = self._resolve_evidence(self._complete(repair + previous + _PAGES_HEAD + blocks + self._reply_budget()))
            raw = _payload(reply)
            parsed = quicklook.parse(reply, self.sources)
        if not isinstance(raw, dict) or not isinstance(raw.get("risks"), list):
            self.telemetry["last_reply"] = reply[-4000:]
            raise LocalInferenceError("The local model did not produce valid answer JSON after one repair. Retry with a larger model or reply budget.", code="invalid_json")
        self.telemetry.update(
            model_calls=sum(getattr(part, "calls", 0) for part in (self._plan, self._complete)),
            pages=len(self.sources), rejected=parsed["dropped"],
            verification=[{"title": risk["title"], "url": risk["sources"][0]["url"],
                           "quote_in_read_page": True} for risk in parsed["risks"]],
            outcome="answer" if parsed["risks"] or parsed["specs"] else "no_supported_findings")
        if parsed["risks"]:
            self._say("self-verifying claim meaning against the quoted pages")
            original_sources = self.sources.copy()
            try:
                self._check()
                verify = (
                    f"Check evidence for {product}. A translated title may be supported "
                    "by an original-language quote. Evaluate meaning, not identical language. "
                    "Reply ONLY {\"verdicts\":[{\"index\":0,\"supported\":true,\"reason\":\"short reason\"}]}. "
                    "Do not add claims. These model opinions do not replace exact quote checks.\n"
                    + json.dumps(parsed["risks"], ensure_ascii=False))
                fitted = self._fit(verify, list(original_sources.items()), self.telemetry["queries"])
                blocks = self._blocks(fitted)
                set_schema(VERIFY_SCHEMA)
                check = _payload(self._complete(verify + _PAGES_HEAD + blocks + self._reply_budget()))
                self.telemetry["self_verify"] = check if isinstance(check, dict) and isinstance(check.get("verdicts"), list) else {"status": "invalid_output"}
            except LocalInferenceError as error:
                self.telemetry["self_verify"] = {"status": error.code, "message": str(error)}
                self._say("self-verification unavailable: " + str(error))
            finally:
                self.sources = original_sources
                set_schema(QUICK_SCHEMA)
        self.telemetry["model_calls"] = sum(getattr(part, "calls", 0) for part in (self._plan, self._complete))
        if self.runtime:
            from app.localruntime import inspect
            self.runtime = inspect(self.url, self.runtime.get("runtime", ""), self.model,
                                   self.runtime.get("settings", {}))
        self._say(f"verified {len(parsed['risks'])} risk(s); {parsed['dropped']} unsupported item(s) rejected")
        return reply

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
            return [f"{self.identity} problems owner reports", f"{self.identity} failures review"]
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

    def _read(self, queries: list[str]) -> list[tuple[str, str]]:
        """Search the queries, then read the pages side by side.

        The reads are the slow part and they do not depend on each other, so
        they go out together on a small pool: five pages fetched one after
        another on a cold connection costs five round trips in sequence,
        which on a CPU-bound run is the difference the reader feels. A few
        spare pages go out with them, and the read stops at `READ_DEADLINE`
        or once `MAX_PAGES` have answered, whichever is first. The order the
        pages appear in the prompt is still the order the queries named
        them, so the model's brief does not change with the fetching. The
        searches go out together only on a hosted search
        (`parallel_search`).

        Each page is cut to `PAGE_CHARS` around the queries' own words
        (`kriko.research.window.focus`), not from the top: a listing's top
        is its menu. The cut text is what the quotes are checked against.
        """
        self._check()

        def _hits(query: str) -> tuple[list, str]:
            try:
                return self._search(query, HITS_PER_QUERY) or [], ""
            except LocalSearchError as error:
                return [], f"search failed for {query!r}: {error}"

        # On a hosted search the queries go out together; their hits are
        # still taken in the queries' order, and the log is written from
        # this thread only.
        if self.parallel_search and len(queries) > 1:
            with ThreadPoolExecutor(max_workers=len(queries)) as pool:
                answered = list(pool.map(_hits, queries))
        else:
            answered = []
            for query in queries:
                self._check()
                answered.append(_hits(query))
        wanted: list[str] = []
        seen: set[str] = set()
        for hits, failure in answered:
            if failure:
                self._say(failure)
            for hit in hits:
                url = str(hit.get("url", "")).strip()
                if not url or url in seen or len(wanted) >= self.max_pages + SPARE_PAGES:
                    continue
                seen.add(url)
                wanted.append(url)
        if not wanted:
            return []
        self._check()

        def _one(url: str) -> str:
            try:
                got = self._fetch(url)
            except Exception:  # noqa: BLE001 - an unreadable page is a miss
                return ""
            text = str(getattr(got, "text", got) or "").strip()
            if len(text) < MIN_PAGE_CHARS:
                return ""
            return focus(text, PAGE_CHARS, queries)

        read: dict[str, str] = {}
        pool = ThreadPoolExecutor(max_workers=min(6, len(wanted)))
        try:
            pending = {pool.submit(_one, url): url for url in wanted}
            deadline = time.monotonic() + READ_DEADLINE
            while pending:
                left = deadline - time.monotonic()
                if left <= 0:
                    self._say(f"stopped waiting for {len(pending)} slow page(s)")
                    break
                done, _ = wait(pending, timeout=min(left, 1.0),
                               return_when=FIRST_COMPLETED)
                for future in done:
                    read[pending.pop(future)] = future.result()
                self._check()
                # Enough are in once MAX_PAGES have text; a spare only
                # stands in for a page that missed.
                if sum(1 for text in read.values() if text) >= self.max_pages:
                    break
        finally:
            # A page still out is abandoned, not waited for: its thread ends
            # on its own timeout and nothing reads what it returns.
            pool.shutdown(wait=False, cancel_futures=True)
        pages: list[tuple[str, str]] = []
        for url in wanted:
            text = read.get(url, "")
            if text and len(pages) < self.max_pages:
                pages.append((url, text))
                self.sources[url] = text
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

    def __call__(self, prompt):
        stage = "verify" if prompt.startswith("Check evidence for ") else self.stage
        return self.owner._measured(stage, self.socket, lambda: self.socket(prompt))
