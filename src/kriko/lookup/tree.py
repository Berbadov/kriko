"""Reading the shape of the evidence back out.

`lookup` answers "what should this reader be told". This module answers the
other question, the one nothing could ask before: *how well supported is what
we are telling them?*

Four signals, reported separately and never collapsed into a score:
contradiction, corroboration, the best source's trust, and how long ago we
last saw the page. A weighted sum would need weights nobody can justify and
would hide which signal fired, so the ordering is lexicographic instead — and
the sort key is a public field, so a reader can disagree with the order by
looking at it rather than by guessing.

Computed at read time from the same rows `rank` uses, and reusing `rank`'s
tier resolution rather than repeating it. Nothing here is written down: install
a better source-tier table and the answer changes with no rebuild.
"""

from dataclasses import asdict, dataclass

from kriko.lookup.rank import (DEFAULT_TIER_TRUST, distinct_source_count,
                               tier_lookup, tier_of, trust_lookup)
from kriko.store.packstore import enabled_pack_ids

#: Sort value for a source with no retrieval date. An absent timestamp is not
#: evidence of staleness, so unknown sorts LAST — least concerning — rather
#: than first. Ranking blank as ancient would put every legacy row at the top
#: of the list on a signal that carries no information at all.
UNKNOWN_STALENESS = "9999"


@dataclass(frozen=True)
class EvidenceRow:
    url: str
    domain: str
    quote: str
    stance: str          # supports | refutes | qualifies
    independent: bool
    source_id: str
    tier: str
    trust: float
    retrieved_at: str    # when WE last saw the page. '' = unknown.
    published_at: str    # when the WORLD published it. Reported, never ranked.


@dataclass(frozen=True)
class ClaimHealth:
    """One claim's identity plus the four signals, each still separate.

    `independent` and `stance` are flags the *producer* supplied. They are
    claims about the evidence, not verified facts, and any surface showing
    them owes the reader that distinction.
    """

    claim_id: str
    pack_id: str
    subject_id: str
    subject_label: str
    title: str
    kind: str
    domain: str
    component: str
    subsystem: str
    severity: str
    refuted_by: int
    supporting_sources: int
    independent_sources: int
    best_tier: str
    best_trust: float
    oldest_retrieved_at: str
    newest_published_at: str

    @property
    def concern(self) -> tuple[int, int, float, str]:
        """The lexicographic sort key, ascending on every element.

        Contradicted first, then fewest independent sources, then weakest best
        source, then stalest. Ascending throughout is what makes the ordering
        explainable in one sentence, and adding a fifth signal later appends an
        element instead of re-tuning four weights.
        """
        return (
            0 if self.refuted_by else 1,
            self.independent_sources,
            self.best_trust,
            self.oldest_retrieved_at or UNKNOWN_STALENESS,
        )


@dataclass(frozen=True)
class ClaimNode:
    health: ClaimHealth
    evidence: tuple[EvidenceRow, ...]


@dataclass(frozen=True)
class SubjectTree:
    subject_id: str
    label: str
    pack_ids: tuple[str, ...]
    claims: tuple[ClaimNode, ...]


def health_json(health: ClaimHealth) -> dict:
    """A ClaimHealth as plain JSON, with its sort key alongside.

    `concern` travels with the row on purpose: an ordering is only
    defensible if the reader can see what produced it.
    """
    return {**asdict(health), "concern": list(health.concern)}


def tree_json(tree: SubjectTree) -> dict:
    return {
        "subject_id": tree.subject_id,
        "label": tree.label,
        "pack_ids": list(tree.pack_ids),
        "claims": [
            {"health": health_json(node.health),
             "evidence": [asdict(row) for row in node.evidence]}
            for node in tree.claims
        ],
    }


_ROWS = """
SELECT c.claim_id, c.pack_id, c.subject_id, c.kind, c.domain, c.severity,
       c.component, c.subsystem,
       s.label            AS subject_label,
       COALESCE(t.title, '') AS title,
       e.stance, e.independent, e.source_id,
       COALESCE(src.domain, '')       AS source_domain,
       COALESCE(src.url, '')          AS url,
       COALESCE(e.quote, '')          AS quote,
       COALESCE(src.retrieved_at, '') AS retrieved_at,
       COALESCE(src.published_at, '') AS published_at
  FROM claims c
  JOIN packs p USING (pack_id)
  JOIN subjects s ON s.subject_id = c.subject_id AND s.pack_id = c.pack_id
  LEFT JOIN claim_text t ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id
                        AND t.lang = ?
  LEFT JOIN evidence e ON e.claim_id = c.claim_id AND e.pack_id = c.pack_id
  LEFT JOIN sources src ON src.source_id = e.source_id
                       AND src.pack_id = e.pack_id
 WHERE p.enabled = 1 AND c.pack_id IN ({marks}){extra}
"""


def _packs(conn, pack_ids):
    return list(pack_ids) if pack_ids else enabled_pack_ids(conn)


def _nodes(conn, pack_ids, *, subject_id=None, lang="en"):
    """Every claim in scope, folded with its evidence. One query, one pass.

    The fold happens in Python rather than SQL because tier resolution is not
    expressible as a join: `tier_of` applies exact, parent-domain, substring
    and default rules in order. Doing it here is what keeps a single
    tier-resolution path in the codebase.
    """
    packs = _packs(conn, pack_ids)
    if not packs:
        return []

    marks = ",".join("?" * len(packs))
    extra = " AND c.subject_id = ?" if subject_id else ""
    args = [lang, *packs] + ([subject_id] if subject_id else [])

    tiers = tier_lookup(conn, packs)
    trusts = trust_lookup(conn, packs)
    unknown = DEFAULT_TIER_TRUST["unknown"]

    grouped: dict[tuple[str, str], dict] = {}
    for row in conn.execute(_ROWS.format(marks=marks, extra=extra), args):
        key = (row["claim_id"], row["pack_id"])
        bucket = grouped.setdefault(key, {"row": row, "evidence": []})
        if row["url"] or row["quote"]:
            tier = tier_of(row["source_domain"], tiers)
            bucket["evidence"].append(EvidenceRow(
                url=row["url"],
                domain=row["source_domain"],
                quote=row["quote"],
                stance=row["stance"] or "supports",
                independent=bool(row["independent"]),
                source_id=row["source_id"] or "",
                tier=tier,
                trust=trusts.get(tier, unknown),
                retrieved_at=row["retrieved_at"],
                published_at=row["published_at"],
            ))

    return [_node(bucket) for bucket in grouped.values()]


def _node(bucket) -> ClaimNode:
    row, evidence = bucket["row"], tuple(bucket["evidence"])

    refuted_by = sum(1 for e in evidence if e.stance == "refutes")
    supporting = [e for e in evidence if e.stance != "refutes"]

    # Distinct source_id, not distinct URL: two quotes off one page are one
    # source, and counting rows would let a single chatty page look
    # corroborated. source_id (not url) is the identity, because a source
    # without a URL — a manual, a scanned bulletin — is still a real, distinct
    # source and must not disappear from the count (backlog B50). Shared with
    # `rank.score_sources` via `distinct_source_count` so the two never
    # disagree about what "independent" means (backlog B49).
    supporting_sources = distinct_source_count(supporting)
    independent_sources = distinct_source_count(supporting, independent_only=True)

    best = max((e for e in supporting), key=lambda e: e.trust, default=None)
    retrieved = sorted(e.retrieved_at for e in supporting if e.retrieved_at)
    published = sorted(e.published_at for e in supporting if e.published_at)

    return ClaimNode(
        health=ClaimHealth(
            claim_id=row["claim_id"],
            pack_id=row["pack_id"],
            subject_id=row["subject_id"],
            subject_label=row["subject_label"],
            title=row["title"],
            kind=row["kind"],
            domain=row["domain"],
            component=row["component"],
            subsystem=row["subsystem"],
            severity=row["severity"],
            refuted_by=refuted_by,
            supporting_sources=supporting_sources,
            independent_sources=independent_sources,
            best_tier=best.tier if best else "unknown",
            best_trust=best.trust if best else 0.0,
            oldest_retrieved_at=retrieved[0] if retrieved else "",
            newest_published_at=published[-1] if published else "",
        ),
        evidence=evidence,
    )


def weakest_claims(conn, pack_ids=None, limit: int = 20, lang: str = "en") -> list[ClaimHealth]:
    """The claims we ship that are least well supported, worst first.

    Claims with **no** evidence at all are excluded, not ranked last: absence
    of sources is what the coverage report answers, and `rank` deliberately
    treats a source-free claim as trust-neutral rather than penalised — an
    interval-based item is not less true for lacking a citation. They remain
    visible in `subject_tree`, so nothing is hidden by this.

    `lang` is a row attribute, same as everywhere else in the engine (see
    `Query.lang` and `/api/query`) — a caller passes the reader's language
    instead of this module silently always answering in one (backlog B51).
    """
    ranked = sorted(
        (node.health for node in _nodes(conn, pack_ids, lang=lang) if node.evidence),
        key=lambda health: (health.concern, health.claim_id, health.pack_id),
    )
    return ranked[:max(0, limit)]


def subject_tree(conn, subject_id: str, pack_ids=None, lang: str = "en") -> SubjectTree:
    """One subject, every claim about it, every piece of evidence under each.

    Unions across packs: a subject with the same identity hashes to the same
    id in every pack, so two packs contradicting each other about one product
    show up here side by side rather than one silently winning.

    An unknown subject is an empty tree, not an error. A fresh install knows
    nothing and that is not a failure.

    `lang` defaults to "en" for a caller that does not know better, but is a
    parameter rather than a hardcoded value — see `weakest_claims`.
    """
    nodes = sorted(
        _nodes(conn, pack_ids, subject_id=subject_id, lang=lang),
        key=lambda node: (node.health.concern, node.health.claim_id, node.health.pack_id),
    )
    return SubjectTree(
        subject_id=subject_id,
        label=nodes[0].health.subject_label if nodes else "",
        pack_ids=tuple(sorted({node.health.pack_id for node in nodes})),
        claims=tuple(nodes),
    )
