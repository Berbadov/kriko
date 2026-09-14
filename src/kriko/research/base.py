"""Where new knowledge comes from — and who pays for it.

Kriko has two research planes, and the difference between them is money rather
than capability:

  **agent** — a coding-agent harness (Claude Code, opencode) does the searching
  and the reading. The subscription is already paid for, so the marginal cost of
  researching one more product is zero. Kriko supplies the brief and stores what
  comes back.

  **api** — Kriko does it itself with a search key and an LLM key. Costs money
  per product, runs unattended, needs nobody watching.

They must produce identical rows, or a pack's provenance would depend on how its
author happened to pay their bills. So the split is behind one interface and
neither implementation gets to invent its own output shape.

What the *pack* supplies, and the engine never hard-codes:

  * the search templates — what questions to ask about this kind of thing
  * the value principle — what makes a claim worth keeping, which for cars is
    "would a buyer learn this from a normal inspection anyway?" and for a
    washing machine is something else entirely
  * the vocabulary the extractor must express its answer in
"""

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: A catalog spells identifiers with underscores; a search box takes words.
#: Only between characters, so a template that deliberately writes `__` as a
#: placeholder keeps it.
_CATALOG_SPELLING = re.compile(r"(?<=\w)_(?=\w)")


#: How many of a subject's search names a brief renders every template with.
#: Two, because the product is a cross product: `packs/cars` ships three names
#: and seven templates, and rendering all of them gave a brief 21 searches
#: where the reader had previously been shown 7 — near-duplicates that bury
#: the ones worth running. The names are narrowest-first (see `query_names`),
#: so the one dropped is always the broadest, which is the one an agent would
#: reach for by itself anyway: it is told the searches are seeds and to write
#: better ones, and widening is the easy direction to go.
MAX_QUERY_NAMES = 2


def searchable(query: str) -> str:
    """A rendered template, as text somebody could actually type.

    The last step before a query is shown to an agent, and it is here rather
    than in a pack because it is a property of *queries*, not of any category:
    an identifier's punctuation is a storage detail, and a substitution that
    resolved to nothing leaves a hole where a word was.

    Deliberately three rules and no more. This is not a place to be clever
    about a category's spelling — a pack that needs its own conventions ships
    `search_name` aliases, which is taste, and taste is pack data. Rewriting
    terms here would be `_MAKE_MAP` again, one layer further in.
    """
    return " ".join(_CATALOG_SPELLING.sub(" ", query).split())


@dataclass(frozen=True)
class Spend:
    """How one operation should spend one model. A *protocol* (B123).

    The two failures are on opposite sides and the middle is narrow. Too little
    batching burns tokens re-sending the same brief for every document. Too
    much piles context until the model stops quoting and starts composing —
    and this codebase catches that at the grounding gate, which means the batch
    is *refused* and the tokens are spent anyway. So the settings that decide
    it are worth naming, recording and choosing from measurements rather than
    leaving as two literals in the middle of a prompt.

    **The shape lives in the engine; the choosing does not.** `kriko/` may not
    import `app/`, and picking a protocol means reading this installation's own
    benchmark rows — which are interface state. So the engine defines what a
    protocol *is* and takes one as an argument; `app/protocols.py` decides
    which. That is the same split `app/providers/` already makes for sockets.

    Nothing here is category-shaped, pack-shaped or provider-shaped: it is
    three numbers about how much text a model is handed at once.
    """

    #: A name, so a measurement can be attributed to it. Two runs of the same
    #: model with different settings are two measurements, and a benchmark
    #: table that recorded only the model would average them into nothing.
    name: str = "standard"
    #: How much of one document is sent. The literal that used to be `[:12000]`
    #: inside a prompt.
    context_chars: int = 12000
    #: How many documents go into one completion call. 1 is a call per
    #: document — the safest for grounding and the most expensive in tokens.
    batch_size: int = 1

    @property
    def context_budget(self) -> int:
        """Roughly how much text one call will carry. The ratio's denominator."""
        return self.context_chars * max(1, self.batch_size)


#: What a plane uses when nobody has measured anything yet. Deliberately the
#: behaviour that existed before protocols did — one document per call, 12k of
#: it — so introducing the mechanism changes no output until a measurement
#: says something better exists.
STANDARD = Spend()


@dataclass(frozen=True)
class Document:
    """A fetched source, before anything has been extracted from it."""
    url: str
    text: str
    site_or_channel: str = ""
    title: str = ""
    source_type: str = "page"       # page | video | structured | manual
    lang: str = ""
    retrieved_at: str = ""


@dataclass(frozen=True)
class ResearchTask:
    """One subject to research, with everything the pack knows about how.

    Deliberately a value object with no database handle. Both implementations
    receive exactly the same brief, and a test can build one by hand.
    """
    subject_id: str
    subject_label: str
    subject_kind: str
    pack_id: str
    identity: dict = field(default_factory=dict)
    # `search_only` aliases are included here and nowhere else: they may widen a
    # query but may never attribute a claim. Collapsing that distinction was
    # design-flaw 3.
    search_aliases: tuple[str, ...] = ()
    #: `search_name` rows: whole phrases a person would type for exactly this
    #: subject. These become the queries where a pack ships them; a
    #: `search_only` fragment above never does, because `LXT common problems`
    #: is a worse search than the label it would have replaced.
    search_names: tuple[str, ...] = ()
    attribution_aliases: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    value_principle: str = ""
    domains: tuple[str, ...] = ()
    #: The languages the pack's own text is written in, primary first, and the
    #: markets its claims are about. Both are pack declarations rather than
    #: engine knowledge — `[pack] languages` / `[pack] markets` in `pack.toml`.
    #:
    #: They exist because until 2026-09-10 nothing anywhere said what language
    #: a query was in. `packs/cars` shipped five English templates and two
    #: Turkish ones and the brief presented all seven as one numbered list, so
    #: an agent could not tell a market convention from a typo. A reader
    #: reported it as "the researches making turkish-english queries".
    languages: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    #: One language code per entry in `queries`, same order. Parallel rather
    #: than a tuple of pairs so `queries` keeps the shape every existing caller
    #: reads; a template that declared none carries the pack's primary.
    query_languages: tuple[str, ...] = ()
    budget_usd: float = 0.0
    max_documents: int = 5

    def language_of(self, query_index: int) -> str:
        """The language template `n` is written in, or the pack's primary."""
        if query_index < len(self.query_languages):
            return self.query_languages[query_index]
        return self.languages[0] if self.languages else ""

    @property
    def query_names(self) -> tuple[str, ...]:
        """What `{label}` and `{alias}` become, best first.

        A pack's `search_name` rows win over its display label, and the reason
        is that they are different kinds of string. A display label exists to
        tell two rows apart in a list, so it carries whatever disambiguates —
        and fed to a search engine, this pack's produced

            Volkswagen Golf 1.5_TSI 150 hp common problems

        a phrase nobody has typed. The reader called it "queries are still
        fucked up" and was right.

        The label stays as the fallback, because a pack that ships no search
        names (`packs/drill/`) must still render queries — and because its
        `search_only` aliases are deliberately *not* used here: those are
        widening fragments, and a fragment standing in for a whole name turns
        `Makita DHP484 common problems` into `DHP 484 common problems`.

        **Narrowest first**, and by length, which needs a word. The store has
        no ordinal for an alias, so `plan_task` reads them back in alphabetical
        order — which put `Volkswagen Golf` ahead of `Volkswagen Golf EA211`
        and made the least specific search the first one in the brief. Sorting
        by length is a *shape* rule and belongs here: a name that contains
        another name is the narrower of the two, in any category, because it
        says everything the shorter one says and one thing more. The tie-break
        is alphabetical so the order is stable across two runs of the same
        subject — a brief that reshuffles itself is a brief nobody can diff.
        """
        ordered = tuple(
            sorted(self.search_names, key=lambda name: (-len(name), name))
        )[:MAX_QUERY_NAMES]
        return ordered or (
            (self.subject_label,) if self.subject_label else ())

    def rendered_plan(self) -> tuple[tuple[str, str], ...]:
        """Each rendered query with the language it is written in.

        The brief groups by this. Presenting a Turkish query and an English one
        as items 3 and 5 of one numbered list is what made a pack's market
        conventions look like a defect — and left the agent nothing to adapt
        *to*, since nothing said which market either belonged to.
        """
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for index, template in enumerate(self.queries):
            lang = self.language_of(index)
            for alias in self.query_names or ("",):
                try:
                    rendered = template.format(
                        label=alias, alias=alias, **self.identity)
                except (KeyError, IndexError):
                    continue
                rendered = searchable(rendered)
                if not rendered or rendered in seen:
                    continue
                seen.add(rendered)
                out.append((rendered, lang))
        return tuple(out)

    def rendered_queries(self) -> tuple[str, ...]:
        """The queries, without their languages. One implementation, above."""
        return tuple(query for query, _ in self.rendered_plan())


@dataclass(frozen=True)
class Finding:
    """One extracted claim, in the shape the store expects.

    Both planes emit this. An agent fills it in by reading; the API plane fills
    it in with an LLM. Neither may invent a quote — `quote` must appear verbatim
    in the document it came from, which is what makes the evidence checkable.
    """
    title: str
    domain: str
    severity: str
    quote: str
    source_url: str
    body: str = ""
    advice: str = ""
    stance: str = "supports"
    component: str = ""


@runtime_checkable
class Researcher(Protocol):
    """The two planes, behind one shape."""

    name: str
    #: "subscription" (already paid for; marginal cost zero) or "per_token".
    #: Named `cost_basis` rather than `cost_model` on purpose — the
    #: domain-free guard bans the word "model" from the engine, and the
    #: exception is not worth taking for a name that reads just as well.
    cost_basis: str

    def brief(self, task: ResearchTask) -> str:
        """What to research, as instructions. The agent plane's real output."""

    def gather(self, task: ResearchTask) -> list[Document]:
        """Fetch candidate sources. May return [] when a human/agent will."""

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """Pull claims out of one document, grounded in verbatim quotes."""
