"""The types the lookup path speaks.

Three callers share them and must keep sharing them, or the engine grows three
subtly different answers to the same question: a site adapter turning a scraped
page into an identity, a human at the CLI, and an agent over MCP.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Query:
    """What the reader knows about the thing in front of them.

    `identity` is what the product *is* — brand, model, engine code. `context`
    is what this particular one has *been through* — a usage figure, hours
    run, charge cycles, age, free text from the ad. The split matters:
    identity selects the subject, context gates the claims. Keep them
    separate: a usage figure belongs in context, never as a column on the
    claim table.
    """

    kind: str
    identity: dict
    context: dict = field(default_factory=dict)
    lang: str = "en"
    packs: tuple[str, ...] | None = None   # None = every enabled pack
    limit: int = 8


@dataclass(frozen=True)
class Resolution:
    subject_ids: tuple[str, ...]
    #: exact | ambiguous | probable | no_match.
    #:
    #: `probable` is the one that is not about the catalog's certainty but about
    #: *ours*: the exact intersection found nothing, and scoring found something
    #: close enough to be worth putting to the reader as a question. A client
    #: must not render it as a match — it renders as "this pack probably covers
    #: this one, confirm?" — and must not render it as nothing, which is the
    #: dead end `score.py` exists to end.
    method: str
    notes: str = ""
    # Soft-narrowing steps that could not be applied, e.g. a stated power that
    # matched no candidate. Never silently dropped — a coverage signal.
    flags: tuple[str, ...] = ()
    #: 0..1 for a scored resolution, 1.0 for an exact one. How sure, not how
    #: many.
    score: float = 1.0
    #: Every subject that was weighed and why, best first — including the ones
    #: that lost. This is what `/api/diagnose/identity` renders and what the
    #: panel shows instead of a silence: a reader who is told "no pack
    #: recognised this" and nothing else cannot tell a missing pack from a
    #: misread page, and those need opposite responses.
    considered: tuple = ()


@dataclass(frozen=True)
class Source:
    url: str
    domain: str
    quote: str
    stance: str
    tier: str
    trust: float


@dataclass(frozen=True)
class Claim:
    claim_id: str
    pack_id: str
    subject_id: str
    subject_label: str
    kind: str
    domain: str
    severity: str
    detection: str
    title: str
    body: str
    advice: str
    relevance: float
    trust: float
    disputed: bool
    via: str                       # how this claim reached the queried subject
    why: tuple[str, ...]           # every reason the score is what it is
    sources: tuple[Source, ...]


@dataclass(frozen=True)
class LookupResult:
    resolution: Resolution
    claims: tuple[Claim, ...]
    coverage: str    # RISKS_FOUND | PROBABLE_MATCH | MATCHED_NO_DATA | NOT_MATCHED
