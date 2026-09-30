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

from app.providers.local_inference import LocalInferenceError
from kriko.research.politeness import LocalSearchError

#: Queries proposed, hits taken per query and pages read in all. Small on
#: purpose: each page costs a model call's worth of context on a CPU.
QUERIES = 3
HITS_PER_QUERY = 3
MAX_PAGES = 5
#: Characters of each page shown to the model, and kept as the text its
#: quotes are checked against. The two are the same on purpose: a quote from
#: beyond what the model saw could only have been invented.
PAGE_CHARS = 6000

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
                 search_provider: str, url: str = ""):
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

        raw = self._plan(_QUERY_ASK.format(n=QUERIES, task=prompt[:4000]))
        try:
            found = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
        except ValueError:
            found = []
        queries = [str(one).strip() for one in found
                   if isinstance(one, str) and one.strip()][:QUERIES]
        if not queries:
            raise LocalInferenceError(
                f"{self.model!r} at {self.url or 'this machine'} did not "
                "propose any search query, so nothing was searched. A larger "
                "model follows this kind of instruction more reliably.")
        return queries

    def _read(self, queries: list[str]) -> list[tuple[str, str]]:
        pages: list[tuple[str, str]] = []
        seen: set[str] = set()
        for query in queries:
            self._check()
            try:
                hits = self._search(query, HITS_PER_QUERY) or []
            except LocalSearchError as error:
                self._say(f"search failed for {query!r}: {error}")
                continue
            for hit in hits:
                url = str(hit.get("url", "")).strip()
                if not url or url in seen or len(pages) >= MAX_PAGES:
                    continue
                seen.add(url)
                got = self._fetch(url)
                text = getattr(got, "text", got) or ""
                text = str(text).strip()[:PAGE_CHARS]
                if text:
                    pages.append((url, text))
                    self.sources[url] = text
        return pages
