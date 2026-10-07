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
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app.providers.local_inference import LocalInferenceError
from kriko.research.politeness import LocalSearchError
from kriko.research.window import focus

#: Queries proposed, hits taken per query and pages read in all. Small on
#: purpose: each page costs a model call's worth of context on a CPU.
QUERIES = 3
FOLLOWUP_QUERIES = 2
HITS_PER_QUERY = 3
MAX_PAGES = 5
FIRST_ROUND_PAGES = 3
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

SELF_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {
                        "type": "string",
                        "enum": ["supported", "unsupported", "unclear"],
                    },
                },
                "required": ["index", "verdict"],
            },
        },
    },
    "required": ["items"],
}

QUOTE_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["index", "quote"],
            },
        },
    },
    "required": ["items"],
}

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

_FOLLOWUP_ASK = (
    "You have read the first search results for this product. Use the pages "
    "below to find evidence gaps, then reply with ONLY a JSON array of up to "
    "{n} new short web search queries. Do not repeat a prior query, do not "
    "include a URL, and do not invent a failure that the pages do not point "
    "toward. Return [] when another search would not help.\n\n"
    "## Task\n\n{task}\n\n## Searches already made\n\n{queries}\n\n"
    "## Pages read in the first round\n\n{pages}"
)

_FOLLOWUP_RETRY = (
    "That reply was not a usable list of new search queries. Reply with ONLY "
    "a JSON array of up to {n} short search queries, or [] if the pages leave "
    "no useful evidence gap. No prose or URLs.\n\n{task}"
)

_SELF_VERIFY_ASK = (
    "Check each candidate risk against the supplied fetched page text. Decide "
    "whether the page supports the same failure and whether the quoted words "
    "appear there. Do not rewrite or add claims. Mark uncertain or missing "
    "evidence unclear. Return ONLY a JSON object with one item for each risk, "
    "using its given index and verdict supported, unsupported, or unclear. "
    "Use one word per verdict, no explanations, and keep the whole object under "
    "100 tokens.\n\n"
    "## Candidate risks\n\n{risks}\n\n## Fetched page excerpts\n\n{pages}"
)

_SELF_VERIFY_RETRY = (
    "The previous reply was not a usable JSON object. Re-check the same "
    "candidate risks and excerpts, then return ONLY "
    '{{"items":[{{"index":0,"verdict":"supported"}}]}} with every risk index. '
    "Use supported, unsupported, or unclear; do not write prose.\n\n{prompt}"
)

_QUOTE_REPAIR_ASK = (
    "Repair only the quotes for these existing risk candidates. Do not add a "
    "risk, change its claim, or invent wording. Return ONLY a JSON object with "
    "an items array of {{index, quote}}. Copy each quote word for word from the "
    "page at that candidate's URL. Include an item only when the page supports "
    "the same failure; otherwise omit it.\n\n"
    "## Candidates\n\n{risks}\n\n## Fetched pages\n\n{pages}"
)

VERIFY_SOURCE_BUDGET = 3600
VERIFY_SOURCE_CHARS = 900
VERIFY_RISK_CHARS = 320
VERIFY_MAX_TOKENS = 128
QUOTE_REPAIR_MAX_TOKENS = 160

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
                 parallel_search: bool = False, verify=None, repair=None):
        self.given_queries = [str(one).strip() for one in (given_queries or [])
                              if str(one).strip()]
        #: True only for a hosted search service built to take concurrent
        #: requests. A local scraper (OpenSERP) asks a public search engine
        #: from the reader's own address, and a burst there is how a run
        #: earns a CAPTCHA, so it stays one query at a time.
        self.parallel_search = parallel_search
        self._plan = plan
        self._complete = complete
        self._verify = verify
        self._repair = repair
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
        self.on_telemetry = None
        self.stage = "waiting"
        self.queries: list[str] = []
        self.model_calls = 0
        self.self_verification: dict | None = None
        self.quote_repair: dict | None = None

    def telemetry(self, stage: str | None = None) -> dict:
        """The local run's safe-to-show counters and current stage."""
        return {
            "stage": stage or self.stage,
            "queries": list(self.queries),
            "pages_read": len(self.sources),
            "pages": list(self.sources),
            "model_calls": self.model_calls,
            "tokens_used": self.tokens_used,
            "self_verification": self.self_verification,
            "quote_repair": self.quote_repair,
        }

    def _report(self, stage: str) -> None:
        self.stage = stage
        if self.on_telemetry is not None:
            self.on_telemetry(self.telemetry())

    @property
    def tokens_used(self) -> int | None:
        total = None
        for part in (self._plan, self._complete, self._verify, self._repair):
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
        self.sources = {}
        self.queries = []
        self.model_calls = 0
        self.self_verification = None
        self.quote_repair = None
        self._report("planning searches")
        self._say(f"asking {self.model} at {self.url or 'this machine'}; "
                  f"searching through {self.search_provider}")
        queries = self._queries(prompt)
        self.queries = list(queries)
        self._report("searching the web")
        self._say("searching: " + "; ".join(queries))
        first_round = self._read(
            queries, max_pages=min(FIRST_ROUND_PAGES, MAX_PAGES))
        if not first_round:
            raise LocalInferenceError(
                f"no page could be read through {self.search_provider} for: "
                + "; ".join(queries)
                + ". Check the internet connection, or start a local "
                "search service (OpenSERP on 127.0.0.1:7000).")
        self._say(f"read {len(first_round)} page(s) in the first round: "
                  + ", ".join(url for url, _ in first_round))
        self._check()
        first_pages = self._fit(prompt, first_round, queries)

        self._report("learning from the first pages")
        followups = self._followup_queries(prompt, queries, first_pages)
        self.queries = [*queries, *followups]
        more_pages: list[tuple[str, str]] = []
        remaining = max(0, MAX_PAGES - len(first_round))
        if followups and remaining:
            self._report("searching follow-up pages")
            self._say("follow-up search: " + "; ".join(followups))
            more_pages = self._read(
                followups,
                max_pages=remaining,
                exclude_urls={url for url, _ in first_round},
            )
            if more_pages:
                self._say(f"read {len(more_pages)} more page(s): "
                          + ", ".join(url for url, _ in more_pages))
        self._report("answering from pages")
        pages = self._fit(
            prompt, [*first_pages, *more_pages], self.queries)
        blocks = "\n\n".join(f"### URL: {url}\n\n{text}" for url, text in pages)
        self.model_calls += 1
        reply = self._complete(prompt + _PAGES_HEAD + blocks + self._reply_budget())
        reply = self._repair_quotes(reply)
        self._report("self-verifying answer")
        self._self_verify(reply)
        self._report("checking cited quotes")
        return reply

    def _repair_quotes(self, reply: str) -> str:
        """Make one bounded quote-only repair before the exact engine check."""
        from app.packauthor import _payload
        from kriko.extract.grounding import loose_span

        payload = _payload(reply)
        risks = payload.get("risks") if isinstance(payload, dict) else None
        if not isinstance(risks, list) or not risks:
            self.quote_repair = {
                "status": "not needed", "checked": 0, "repaired": 0,
                "unrepaired": 0,
            }
            return reply

        candidates: list[tuple[int, dict]] = []
        for index, risk in enumerate(risks):
            if not isinstance(risk, dict):
                continue
            url = str(risk.get("url") or "").strip()
            if url not in self.sources:
                continue
            quote = str(risk.get("quote") or "").strip()
            if quote and loose_span(self.sources[url], quote):
                continue
            candidates.append((index, risk))
            if len(candidates) >= 6:
                break

        if not candidates:
            self.quote_repair = {
                "status": "not needed", "checked": 0, "repaired": 0,
                "unrepaired": 0,
            }
            return reply
        if self._repair is None:
            self.quote_repair = {
                "status": "unavailable", "checked": len(candidates),
                "repaired": 0, "unrepaired": len(candidates),
            }
            return reply

        compact = []
        excerpts: dict[str, str] = {}
        for index, risk in candidates:
            url = str(risk.get("url") or "").strip()
            title = str(risk.get("title") or "")[:100]
            why = str(risk.get("why") or "")[:VERIFY_RISK_CHARS]
            compact.append({
                "index": index, "title": title, "claim": why, "url": url,
                "old_quote": str(risk.get("quote") or "")[:VERIFY_RISK_CHARS],
            })
            if url not in excerpts:
                terms = [*title.split(), *why.split()]
                excerpts[url] = focus(
                    self.sources[url], VERIFY_SOURCE_CHARS, terms)

        prompt = _QUOTE_REPAIR_ASK.format(
            risks=json.dumps(compact, ensure_ascii=False),
            pages="\n\n".join(
                f"URL: {url}\n{text}" for url, text in excerpts.items()),
        )
        self._say(f"repairing quotes for {len(candidates)} risk(s) that did not ground")
        self._report("repairing cited quotes")
        self._check()
        self.model_calls += 1
        try:
            repaired = _payload(self._repair(prompt))
        except LocalInferenceError as error:
            self._say(f"quote repair unavailable: {error}")
            repaired = {}

        replacements: dict[int, str] = {}
        allowed = {index: str(risk.get("url") or "").strip()
                   for index, risk in candidates}
        for item in repaired.get("items", []) if isinstance(repaired, dict) else []:
            if not isinstance(item, dict):
                continue
            repair_index = item.get("index")
            quote = str(item.get("quote") or "").strip()
            if (isinstance(repair_index, int) and not isinstance(repair_index, bool)
                    and repair_index in allowed and quote):
                exact = loose_span(self.sources[allowed[repair_index]], quote)
                if exact:
                    replacements[repair_index] = exact

        for index, quote in replacements.items():
            risks[index]["quote"] = quote
        repaired_count = len(replacements)
        self.quote_repair = {
            "status": "complete" if repaired_count == len(candidates)
            else "partial" if repaired_count else "unrepaired",
            "checked": len(candidates), "repaired": repaired_count,
            "unrepaired": len(candidates) - repaired_count,
        }
        if repaired_count:
            self._say(f"grounded {repaired_count} repaired quote(s)")
            return json.dumps(payload, ensure_ascii=False)
        return reply

    def _followup_queries(self, task: str, previous: list[str],
                          pages: list[tuple[str, str]]) -> list[str]:
        """Ask once, with one repair, for searches learned from first-round pages.

        This is deliberately a small second round: it can add evidence but
        cannot expand the run past MAX_PAGES or repeatedly search a page set.
        If the local model cannot produce a query list, the first-round answer
        remains usable.
        """
        # Benchmark cases and callers supplying fixed queries keep an exact
        # search set; adding inferred queries would change what they measure.
        if self.given_queries or not pages or len(pages) >= MAX_PAGES:
            return []
        samples = "\n\n".join(
            f"URL: {url}\n{text[:1200]}" for url, text in pages)
        prompt = _FOLLOWUP_ASK.format(
            n=FOLLOWUP_QUERIES,
            task=task[:PLAN_CHARS],
            queries=json.dumps(previous, ensure_ascii=False),
            pages=samples,
        )
        self.model_calls += 1
        try:
            raw = self._plan(prompt)
        except LocalInferenceError as error:
            self._say(f"follow-up planner unavailable: {error}")
            return []
        values = self._array(raw)
        if values == []:
            return []
        queries = self._usable(
            raw, maximum=FOLLOWUP_QUERIES, exclude=previous)
        if queries:
            return queries

        self._say("the follow-up planner's reply held no usable query; asking once more")
        self.model_calls += 1
        try:
            raw = self._plan(_FOLLOWUP_RETRY.format(
                n=FOLLOWUP_QUERIES, task=prompt))
        except LocalInferenceError as error:
            self._say(f"follow-up query repair unavailable: {error}")
            return []
        if self._array(raw) == []:
            return []
        return self._usable(
            raw, maximum=FOLLOWUP_QUERIES, exclude=previous)

    @staticmethod
    def _array(raw: str) -> list | None:
        """Read a JSON array from a model reply, or return None if malformed."""
        try:
            start, end = raw.index("["), raw.rindex("]") + 1
            found = json.loads(raw[start:end])
        except ValueError:
            return None
        return found if isinstance(found, list) else None

    def _self_verify(self, reply: str) -> None:
        """Keep a bounded model check beside the answer; grounding stays exact."""
        from app.packauthor import _payload

        candidates = _payload(reply).get("risks") or []
        risks = [(index, one) for index, one in enumerate(candidates)
                 if isinstance(one, dict)][:6]
        if not risks:
            self.self_verification = {
                "status": "complete", "verdict": "no risk claims",
                "checked": 0, "supported": 0, "unsupported": 0,
                "unclear": 0, "items": [],
            }
            return
        if self._verify is None:
            self.self_verification = {
                "status": "unavailable", "verdict": "model check unavailable",
                "checked": 0, "supported": 0, "unsupported": 0,
                "unclear": len(risks), "items": [],
            }
            return

        prompt = self._verification_prompt(risks)
        self._check()
        self.model_calls += 1
        try:
            raw = self._verify(prompt)
        except LocalInferenceError as error:
            self._say(f"model self-check unavailable: {error}")
            self.self_verification = {
                "status": "unavailable", "verdict": "model check unavailable",
                "checked": 0, "supported": 0, "unsupported": 0,
                "unclear": len(risks), "items": [],
            }
            return
        parsed = _payload(raw)
        if not isinstance(parsed.get("items"), list):
            self._say("the model self-check did not return JSON; asking once more")
            self.model_calls += 1
            try:
                raw = self._verify(_SELF_VERIFY_RETRY.format(prompt=prompt))
            except LocalInferenceError as error:
                self._say(f"model self-check repair unavailable: {error}")
                parsed = {}
            else:
                parsed = _payload(raw)
        self.self_verification = self._clean_verdict(
            parsed, [index for index, _ in risks])

    def _verification_prompt(self, risks: list[tuple[int, dict]]) -> str:
        compact = []
        cited: dict[str, str] = {}
        for index, risk in risks:
            url = str(risk.get("url") or "").strip()
            quote = str(risk.get("quote") or "").strip()
            compact.append({
                "index": index,
                "title": str(risk.get("title") or "")[:100],
                "claim": str(risk.get("why") or "")[:VERIFY_RISK_CHARS],
                "url": url,
                "quote": quote[:VERIFY_RISK_CHARS],
            })
            if url and url in self.sources and url not in cited:
                text = self.sources[url]
                position = text.find(quote) if quote else -1
                if position >= 0:
                    start = max(0, position - 250)
                    text = text[start:position + len(quote) + 350]
                cited[url] = text

        pages = []
        left = VERIFY_SOURCE_BUDGET
        for url, text in cited.items():
            if left <= 0:
                break
            excerpt = text[:min(VERIFY_SOURCE_CHARS, left)]
            pages.append(f"URL: {url}\n{excerpt}")
            left -= len(excerpt)
        if not pages:
            pages.append("No fetched page matches the candidate URLs.")
        return _SELF_VERIFY_ASK.format(
            risks=json.dumps(compact, ensure_ascii=False),
            pages="\n\n".join(pages),
        )

    @staticmethod
    def _clean_verdict(payload: dict, risk_indices: list[int]) -> dict:
        values = payload.get("items") if isinstance(payload, dict) else None
        items: dict[int, str] = {}
        allowed = set(risk_indices)
        for value in values or []:
            if not isinstance(value, dict):
                continue
            index, verdict = value.get("index"), value.get("verdict")
            if (isinstance(index, int) and not isinstance(index, bool)
                    and index in allowed
                    and isinstance(verdict, str)
                    and verdict in {"supported", "unsupported", "unclear"}):
                items[index] = verdict
        checked = [{"index": index, "verdict": items.get(index, "unclear")}
                   for index in risk_indices]
        counts = {name: sum(item["verdict"] == name for item in checked)
                  for name in ("supported", "unsupported", "unclear")}
        if counts["unsupported"] == len(risk_indices):
            verdict = "unsupported"
        elif counts["unsupported"]:
            verdict = "mixed"
        elif counts["unclear"]:
            verdict = "inconclusive"
        else:
            verdict = "supported"
        complete = len(items) == len(risk_indices)
        return {
            "status": "complete" if complete else "incomplete",
            "verdict": verdict,
            "checked": len(items),
            **counts,
            "items": checked,
        }

    def reconcile_grounding(self, grounded_indices: list[int]) -> None:
        """Let the engine's exact quote check overrule model optimism."""
        check = self.self_verification
        if not isinstance(check, dict):
            return
        original = str(check.get("verdict") or "")
        grounded = set(grounded_indices)
        items = check.get("items")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if (isinstance(index, int) and not isinstance(index, bool)
                    and index not in grounded and item.get("verdict") == "supported"):
                item["verdict"] = "unsupported"
        counts = {name: sum(
            isinstance(item, dict) and item.get("verdict") == name
            for item in items
        ) for name in ("supported", "unsupported", "unclear")}
        checked = [item for item in items if isinstance(item, dict)]
        if counts["unsupported"] and counts["supported"] == 0:
            verdict = "unsupported"
        elif counts["unsupported"]:
            verdict = "mixed"
        elif counts["unclear"]:
            verdict = "inconclusive"
        else:
            verdict = "supported" if checked else "no risk claims"
        check.update({
            "model_verdict": original,
            "verdict": verdict,
            "supported": counts["supported"],
            "unsupported": counts["unsupported"],
            "unclear": counts["unclear"],
            "engine_grounded": len(grounded),
        })

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
        room = allowed() - len(prompt) - len(_PAGES_HEAD) - len(self._reply_budget())
        count = len(pages)
        while count > 1 and room // count < MIN_SHARE:
            count -= 1
        share = max(MIN_SHARE // 2, room // max(1, count) - 40)
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
        # invent either first-round or follow-up queries would quietly change
        # what the run measured.
        if self.given_queries:
            return list(self.given_queries)[:QUERIES]
        task = prompt[:PLAN_CHARS]
        self.model_calls += 1
        queries = self._usable(self._plan(_QUERY_ASK.format(n=QUERIES, task=task)))
        if not queries:
            # One repair, said plainly: a small model that answered with a
            # url or prose once usually answers the plain ask right.
            self._say("the planner's reply held no usable query; asking once more")
            self.model_calls += 1
            queries = self._usable(self._plan(_QUERY_RETRY.format(n=QUERIES, task=task)))
        if not queries:
            raise LocalInferenceError(
                f"{self.model!r} at {self.url or 'this machine'} did not "
                "propose any search query, so nothing was searched. A larger "
                "model follows this kind of instruction more reliably.")
        return queries

    @staticmethod
    def _usable(raw: str, *, maximum: int = QUERIES,
                exclude: list[str] | tuple[str, ...] = ()) -> list[str]:
        """The search queries in a planner's reply: no urls, no sentences,
        no repeats, at most `QUERIES`."""
        found = LocalAsker._array(raw) or []
        queries: list[str] = []
        lowered = {str(one).strip().casefold() for one in exclude}
        for one in found:
            text = str(one).strip()
            low = text.casefold()
            if (not text or low in lowered or "://" in text or low.startswith("www.")
                    or len(text.split()) > QUERY_WORDS):
                continue
            lowered.add(low)
            queries.append(text)
            if len(queries) >= maximum:
                break
        return queries

    def _read(self, queries: list[str], *, max_pages: int = MAX_PAGES,
              exclude_urls: set[str] | None = None) -> list[tuple[str, str]]:
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
        if max_pages <= 0:
            return []

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
        seen = set(exclude_urls or ())
        for hits, failure in answered:
            if failure:
                self._say(failure)
            for hit in hits:
                url = str(hit.get("url", "")).strip()
                if (not url or url in seen
                        or len(wanted) >= max_pages + SPARE_PAGES):
                    continue
                seen.add(url)
                wanted.append(url)
        if not wanted:
            return []
        self._check()
        self._report("reading pages")

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
                if sum(1 for text in read.values() if text) >= max_pages:
                    break
        finally:
            # A page still out is abandoned, not waited for: its thread ends
            # on its own timeout and nothing reads what it returns.
            pool.shutdown(wait=False, cancel_futures=True)
        pages: list[tuple[str, str]] = []
        for url in wanted:
            text = read.get(url, "")
            if text and len(pages) < max_pages:
                pages.append((url, text))
                self.sources[url] = text
        return pages
