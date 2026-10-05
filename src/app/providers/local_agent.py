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

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app.providers.local_inference import LocalInferenceError
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

QUERY_SCHEMA = {"type": "array", "items": {"type": "string"}}

_QUERY_ASK = (
    "You are choosing web searches. Read the task below and reply with ONLY a "
    "JSON array of {n} short web search queries that would find documented "
    "problems, failures and owner reports about the product it names. No "
    "prose.\n\n## Task\n\n{task}"
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
                 given_queries: list[str] | None = None):
        self.given_queries = [str(one).strip() for one in (given_queries or [])
                              if str(one).strip()]
        self._plan = plan
        self._complete = complete
        self._search = search
        self._fetch = fetch
        self.model = model
        self.search_provider = search_provider
        self.url = url
        self.sources: dict[str, str] = {}
        self.on_action = None
        self.check_cancelled = None
        self.replies = None
        self.note = ""

    @property
    def tokens_used(self) -> int | None:
        total = None
        for part in (self._plan, self._complete):
            value = getattr(part, "tokens_used", None)
            if isinstance(value, int) and not isinstance(value, bool):
                total = (total or 0) + value
        return total

    def _say(self, line: str) -> None:
        if self.on_action is not None:
            self.on_action(line)

    def _check(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()

    def ask(self, prompt: str) -> str:
        self._check()
        self._say(f"asking {self.model} at {self.url or 'this machine'}; "
                  f"searching through {self.search_provider}")
        queries = self._queries(prompt)
        self._say("searching: " + "; ".join(queries))
        pages = self._read(queries)
        if not pages:
            raise LocalInferenceError(
                f"no page could be read through {self.search_provider} for: "
                + "; ".join(queries)
                + ". Check the internet connection, or start a local "
                "search service (OpenSERP on 127.0.0.1:7000).")
        self._say(f"read {len(pages)} page(s): "
                  + ", ".join(url for url, _ in pages))
        self._check()
        blocks = "\n\n".join(f"### URL: {url}\n\n{text}" for url, text in pages)
        return self._complete(prompt + _PAGES_HEAD + blocks)

    def _queries(self, prompt: str) -> list[str]:
        import json

        # A case may name its own queries (B185): the fixed set's queries
        # are part of its versioned ground truth, and letting the model
        # invent its own would quietly change what the run measured.
        if self.given_queries:
            return list(self.given_queries)[:QUERIES]
        raw = self._plan(_QUERY_ASK.format(n=QUERIES, task=prompt[:4000]))
        try:
            found = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
        except ValueError:
            found = []
        queries: list[str] = []
        lowered: set[str] = set()
        for one in found:
            text = str(one).strip()
            low = text.casefold()
            if not text or low in lowered:
                continue
            lowered.add(low)
            queries.append(text)
            if len(queries) >= QUERIES:
                break
        if not queries:
            raise LocalInferenceError(
                f"{self.model!r} at {self.url or 'this machine'} did not "
                "propose any search query, so nothing was searched. A larger "
                "model follows this kind of instruction more reliably.")
        return queries

    def _read(self, queries: list[str]) -> list[tuple[str, str]]:
        """Search every query at once, then read the pages side by side.

        The reads are the slow part and they do not depend on each other, so
        they go out together on a small pool: five pages fetched one after
        another on a cold connection costs five round trips in sequence,
        which on a CPU-bound run is the difference the reader feels. A few
        spare pages go out with them, and the read stops at `READ_DEADLINE`
        or once `MAX_PAGES` have answered, whichever is first. The order the
        pages appear in the prompt is still the order the queries named
        them, so the model's brief does not change with the fetching.

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

        # The searches do not depend on each other either, so they go out
        # together too; their hits are still taken in the queries' order,
        # and the log is written from this thread only.
        with ThreadPoolExecutor(max_workers=max(1, len(queries))) as pool:
            answered = list(pool.map(_hits, queries))
        wanted: list[str] = []
        seen: set[str] = set()
        for hits, failure in answered:
            if failure:
                self._say(failure)
            for hit in hits:
                url = str(hit.get("url", "")).strip()
                if not url or url in seen or len(wanted) >= MAX_PAGES + SPARE_PAGES:
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
                if sum(1 for text in read.values() if text) >= MAX_PAGES:
                    break
        finally:
            # A page still out is abandoned, not waited for: its thread ends
            # on its own timeout and nothing reads what it returns.
            pool.shutdown(wait=False, cancel_futures=True)
        pages: list[tuple[str, str]] = []
        for url in wanted:
            text = read.get(url, "")
            if text and len(pages) < MAX_PAGES:
                pages.append((url, text))
                self.sources[url] = text
        return pages
