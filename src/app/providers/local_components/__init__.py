"""The local agent: one `ask`, five named components, no leg it stands on alone.

An `ask` for the local model — the quick look and the pack author with no
CLI. The coding agents that answer `ask(prompt)` bring their own web search;
a model served from this machine does not: it reads what it is given. So
this package does the legwork a CLI does for itself, and does it as
**components**, because the reader's own words asked for it that way:

> "I'd like to enrichen our structure and the add many components possible
> to make sure that it works yet being a small model."

One `ask` runs the components in this order, and every stage is said aloud
through `on_action`, so the run's own record tells the reader what the model
spent its context on:

1. **Plan** (`plan.propose`) — the model proposes a few search queries, with
   a repair loop: a reply that is not a JSON array is quoted back and asked
   again, bounded, and a model that never holds the shape falls back to the
   plain queries a reader would type.
2. **Search round one** (`search.gather`) — the queries are searched, the
   hits deduped, the pages read side by side.
3. **Search round two** (`plan.refine` + another gather) — only when round
   one found little, the model names what the first searches missed, and the
   union of both rounds is what the run has.
4. **Triage** (`triage.choose`) — the pages ranked and fitted to the
   model's *own* context, so a small context is spent on the best few
   pages whole rather than the head of everything.
5. **Answer** — one completion with the pages beside the brief, and the
   answer's *shape* repaired once: a reply with no JSON object in it (the
   small model's prose answer, real risks and all) is asked for the shape
   again, the same repair the planner does for queries.
6. **Self-check** (`verify.check`) — the model reads its own answer against
   the pages it cites; the verdict is kept on `verification`, beside the
   answer, not enforced here.

The pages it read are kept by address in `sources`, the same slot the API
agent fills, so `quicklook.parse` can require every quote to be *in* the
page it cites. A small model does not get to write a risk nobody published:
a quote that is not on a fetched page is dropped, and so is a risk with no
page — and since triage, what is kept is exactly the text the model saw.

Nothing here decides what the answer is worth. It is the same brief, the
same reply shape and the same grounding as every other door; only the
reader of the web differs.
"""

import time
from collections.abc import Callable

from app.providers.local_inference import LocalInferenceError

from . import evidence, identity, plan, search, triage, verify

#: Queries proposed, hits taken per query and pages kept in all. Small on
#: purpose: each page costs a model call's worth of context on a CPU.
QUERIES = 3
HITS_PER_QUERY = 3
MAX_PAGES = 5

#: The most of one page the model is ever shown. The grounding contract: the
#: text kept in `sources` is these same characters, so a quote from beyond
#: what the model saw could only have been invented.
PAGE_CHARS = 6000

#: Below this many readable pages after round one, round two runs. A round
#: two that finds nothing still costs its search round, so it runs only when
#: round one left room to want more.
MORE_BELOW = 3

#: Completion headroom, in tokens, for a model that thinks before it writes.
#: The socket's own default (1024) cut one such model off before it wrote
#: anything at all — the reply budget spent on reasoning, `finish_reason`
#: "length", an empty answer — which on the old three-step script ended the
#: run at its very first call. Headroom, not a target: a reply that needs
#: this much of it is a slow run, and the run's own timeout still bounds it.
PLAN_MAX_TOKENS = 2048
REPLY_MAX_TOKENS = 8192

#: How hard the model is asked to think before it writes. An OpenAI-surface
#: value, not a product's private switch: a reasoning model left to think
#: spent the reply's whole budget on thinking and wrote nothing at all, and
#: a *low* effort was a hint it did not honor — the full budget burned again
#: — while *none* answered the same task in a fraction of it. The quick
#: look is chat-speed by design; a server that does not know the value
#: drops it and answers (`local_inference`'s 400 path), and a model with no
#: thinking to do ignores it.
REASONING_EFFORT = "none"

QUERY_SCHEMA = {"type": "array", "items": {"type": "string"}}

_PAGES_HEAD = (
    "\n\n## Pages you fetched\n\n"
    "These are the only sources you have. Cite only these URLs, exactly. Every "
    "quote must be copied verbatim from the page it cites. If the pages do not "
    "support a claim, leave it out rather than guess.\n\n"
)


_REPLY_AGAIN = (
    "\n\n## Your last reply had no JSON object in it\n\n"
    "You answered in prose. Reply again with ONE JSON object, in a ```json "
    "fence, as the last thing you say — the object the task's ## Reply section "
    "shows. Every risk carries its `url` and a `quote` copied verbatim from "
    "that page. No prose outside the fence.\n\n"
    "## Your last reply, for the risks it found\n\n{last}"
)


class LocalAsker:
    """`ask(prompt) -> str`, answering from pages it fetched itself.

    Shaped like the harness researchers so the jobs that `ask` take it without
    knowing the difference: `on_action`, `check_cancelled` and `replies` are
    set by the job, `sources`, `search_provider` and `verification` are read
    back.
    """

    name = "local"
    cost_basis = "self_hosted"

    def __init__(self, plan_socket, complete, search, fetch, *, model: str,
                 search_provider: str, url: str = "",
                 given_queries: list[str] | None = None,
                 parallel_search: bool = False,
                 given_sources: dict[str, str] | None = None,
                 requested_specs: list[str] | None = None):
        self.given_sources = given_sources
        self.requested_specs = requested_specs
        self.metrics: list[dict] = []
        self.parallel_search = parallel_search
        self.given_queries = [str(one).strip() for one in (given_queries or [])
                              if str(one).strip()]
        self._plan = plan_socket
        self._complete = complete
        self._search = search
        self._fetch = fetch
        self.model = model
        self.search_provider = search_provider
        self.url = url
        self.sources: dict[str, str] = {}
        #: The self-check's verdict on the last answer (`verify.check`):
        #: `unsupported` names the risks its own pages do not carry.
        self.verification: dict | None = None
        self.on_action: Callable[[str], None] | None = None
        self.check_cancelled: Callable[[], None] | None = None
        self.replies = None
        self.note = ""

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
        if self.on_action is not None:
            self.on_action(line)

    def _check(self) -> None:
        if self.check_cancelled is not None:
            self.check_cancelled()

    def ask(self, prompt: str) -> str:
        self.sources = {}
        self.verification = None
        self.metrics = []
        self._check()
        self._say(f"asking {self.model} at {self.url or 'this machine'}; "
                  f"searching through {self.search_provider}")
        if prompt.startswith("# Quick look:"):
            prompt += identity.GUIDANCE
        if self.given_sources is not None:
            queries = self.given_queries
            pages = list(self.given_sources.items())
            self._say(f"using {len(pages)} supplied evidence document(s)")
        else:
            queries, pages = self._gather(prompt)
        return self._respond(prompt, queries, pages)

    def _gather(self, prompt):
        queries = self._measured("plan", self._plan, lambda: plan.propose(
            prompt, self._plan, given=self.given_queries,
                               queries=QUERIES, say=self._say,
                               check=self._check))
        self._say("searching: " + "; ".join(queries))
        seen: set[str] = set()
        searched: set[str] = set()
        pages, _ = self._measured("search", None, lambda: search.gather(
            self._search, self._fetch, queries, seen=seen, searched=searched,
            limit=MAX_PAGES, hits_per_query=HITS_PER_QUERY,
            say=self._say, check=self._check, parallel=self.parallel_search))
        if len(pages) < MORE_BELOW:
            more = self._measured("refine", self._plan, lambda: plan.refine(
                prompt, queries, [url for url, _ in pages],
                               self._plan, queries=QUERIES,
                               say=self._say, check=self._check))
            if more:
                self._say("searching again: " + "; ".join(more))
                round_two, _ = self._measured("search_refined", None, lambda: search.gather(
                    self._search, self._fetch, more, seen=seen,
                    searched=searched, limit=MAX_PAGES,
                    hits_per_query=HITS_PER_QUERY,
                    say=self._say, check=self._check, parallel=self.parallel_search))
                pages = pages + round_two
        if not pages:
            raise LocalInferenceError(
                f"no page could be read through {self.search_provider} for: "
                + "; ".join(queries)
                + ". Check the internet connection, or start a local "
                "search service (OpenSERP on 127.0.0.1:7000).")
        return queries, pages

    def _respond(self, prompt, queries, pages):
        self._say(f"read {len(pages)} page(s): "
                  + ", ".join(url for url, _ in pages))
        self._check()
        # Reserve an answer inside the runtime's actual window. An 8192-token
        # reply reservation leaves no evidence room in a 4096-token context.
        context = getattr(self._complete, "context_tokens", None)
        if callable(context):
            window = context()
            cap = getattr(self._complete, "max_tokens", None)
            if isinstance(cap, int) and cap > 0:
                self._complete.max_tokens = min(cap, max(256, window // 4))
        chosen = self._measured("triage", None, lambda: triage.choose(
            pages, task=prompt + _PAGES_HEAD, queries=queries,
            budget=triage.budget_of(self._complete),
            at_most=MAX_PAGES, page_cap=PAGE_CHARS))
        if self.given_sources is not None:
            # Controlled tests give every provider the same complete corpus.
            # Refuse an oversized corpus; truncating it changes the test.
            chosen = pages
        # The grounding contract: what `sources` keeps is what the model sees,
        # the same truncated characters, so `quicklook.parse` checks quotes
        # against exactly the text that was in the prompt.
        self.sources = {url: text for url, text in chosen}
        self._say(f"sending {len(chosen)} of {len(pages)} page(s), sized "
                  "to this model's own context")
        blocks = "\n\n".join(f"### URL: {url}\n\n{text}" for url, text in chosen)
        answer = self._measured("answer", self._complete, lambda: self._answer(
            prompt + _PAGES_HEAD + blocks, quick=prompt.startswith("# Quick look:")))
        # The answer's shape repaired, once: a small model that found real
        # risks and set them out in prose still gave the door nothing it can
        # render. The same repair the planner does for the queries, done to
        # the reply, against the one fence reader every door reads with.
        from app.packauthor import read_payload

        payload = read_payload(answer)[0]
        quick = prompt.startswith("# Quick look:")
        if not payload or (quick and not self._quick_payload(payload)):
            self._say("the reply carried no JSON object; "
                      "asking for the shape again")
            try:
                retry = self._measured("repair", self._complete, lambda: self._answer(
                    prompt + _PAGES_HEAD + blocks
                    + _REPLY_AGAIN.format(last=answer[:1000]), quick=quick))
            except Exception as error:  # noqa: BLE001 - the first answer stands
                self._say(f"the shape repair could not run: {error}")
                retry = ""
            repaired = read_payload(retry)[0]
            if repaired and (not quick or self._quick_payload(repaired)):
                answer = retry
            else:
                self._say("the second reply carried no JSON object either; "
                          "keeping the first")
        self.last_finish_reason = getattr(self._complete, "last_finish_reason", "")
        self._check()
        self.verification = self._measured("verify", self._complete, lambda:
            verify.check(self._complete, answer, chosen, say=self._say))
        if self.verification.get("error"):
            self.metrics[-1]["failed"] = True
            self.metrics[-1]["error"] = self.verification["error"]
        return answer

    @staticmethod
    def _quick_payload(payload) -> bool:
        return isinstance(payload, dict) and any(
            isinstance(payload.get(key), list) for key in ("risks", "specs"))

    def _answer(self, prompt: str, *, quick: bool) -> str:
        """Constrain Quick Look JSON without constraining other agent tasks."""
        from copy import deepcopy
        from app.quicklook import REPLY_SCHEMA

        schema = getattr(self._complete, "_schema", None)
        if quick and schema is not None:
            constrained = deepcopy(REPLY_SCHEMA)
            if self.requested_specs is not None:
                constrained["properties"]["specs"]["maxItems"] = len(self.requested_specs)
                if self.requested_specs:
                    constrained["properties"]["specs"]["items"]["properties"]["name"] = {
                        "type": "string", "enum": self.requested_specs}
            # A small model misspells addresses even when the page is beside
            # it. The runtime must choose a fetched URL, not generate one.
            for key in ("risks", "specs"):
                constrained["properties"][key]["items"]["properties"]["url"] = {
                    "type": "string", "enum": list(self.sources)}
            # Choose quote text directly from a page. Generating it freely
            # made small multilingual models translate or misspell quotes.
            variants = []
            for url, text in self.sources.items():
                quotes = evidence.quotes(text, prompt, spec_names=self.requested_specs or [])
                if not quotes:
                    continue
                for quote in quotes:
                    item = deepcopy(constrained["properties"]["risks"]["items"])
                    item["properties"]["url"] = {"type": "string", "enum": [url]}
                    item["properties"]["quote"] = {"type": "string", "enum": [quote]}
                    # Extractive claims: the model selects the evidence, but
                    # cannot attach an unrelated fault to a valid quotation.
                    # Keep the source language; fluency must not invent facts.
                    item["properties"]["title"] = {"type": "string", "enum": [quote[:160]]}
                    item["properties"]["why"] = {"type": "string", "enum": [quote]}
                    item["additionalProperties"] = False
                    variants.append(item)
            if variants:
                constrained["properties"]["risks"]["items"] = {"anyOf": variants}
            else:
                constrained["properties"]["risks"]["maxItems"] = 0
            self._complete._schema = constrained
            prompt += ("\nFor each specification, return only the requested field's value "
                       "and unit. Omit the product, market, year and explanatory sentence "
                       "from the value. Compatibility and absence of documented faults "
                       "are context, not risks.\n")
        try:
            allowed = getattr(self._complete, "prompt_chars_allowed", None)
            if callable(allowed) and len(prompt) > allowed():
                raise LocalInferenceError(
                    "The local model's context is too small for the task and "
                    "its sources. Increase the context in the model server, "
                    "then retry Quick Look.")
            return self._complete(prompt)
        finally:
            if schema is not None:
                self._complete._schema = schema
