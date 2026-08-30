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

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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
    attribution_aliases: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    value_principle: str = ""
    domains: tuple[str, ...] = ()
    budget_usd: float = 0.0
    max_documents: int = 5

    def rendered_queries(self) -> tuple[str, ...]:
        """Templates with this subject's own words substituted in."""
        out = []
        for template in self.queries:
            for alias in (self.subject_label, *self.search_aliases) or ("",):
                try:
                    rendered = template.format(
                        label=self.subject_label, alias=alias, **self.identity)
                except (KeyError, IndexError):
                    continue
                if rendered not in out:
                    out.append(rendered)
        return tuple(out)


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
