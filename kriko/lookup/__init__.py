"""One lookup path, for every product category and every caller.

    identity + context  ->  subjects  ->  claims  ->  gated  ->  ranked  ->  capped

This replaces `backend/core/matcher.py` and `backend/core/resolver.py`, which
together held 876 lines of car knowledge. Nothing here knows what a car is; the
rules arrive as pack rows. The proof is mechanical rather than aspirational:
`test_kriko_core_never_imports_a_domain_layer` forbids this package from
importing `packs/`, and the drill pack's suite runs the same code path over
charge cycles and chuck sizes.
"""

from kriko.lookup.conditions import Condition, evaluate_all
from kriko.lookup.match import expand, resolve
from kriko.lookup.query import Claim, LookupResult, Query, Resolution
from kriko.lookup.rank import explain, relevance, score_sources, tier_lookup, trust_lookup
from kriko.store.packstore import enabled_pack_ids

__all__ = ["lookup", "Query", "Resolution", "Claim", "LookupResult"]


def _pack_weights(conn) -> dict[str, float]:
    return {r["pack_id"]: float(r["weight"])
            for r in conn.execute("SELECT pack_id, weight FROM pack_trust")}


def _conditions_for(conn, claim_id, pack_id) -> list[Condition]:
    return [
        Condition(key=r["key"], op=r["op"], value_num=r["value_num"],
                  value_text=r["value_text"], on_missing=r["on_missing"],
                  weight=float(r["weight"]))
        for r in conn.execute(
            "SELECT key, op, value_num, value_text, on_missing, weight"
            " FROM claim_conditions WHERE claim_id = ? AND pack_id = ?"
            " ORDER BY seq", (claim_id, pack_id))
    ]


def lookup(conn, query: Query) -> LookupResult:
    pack_ids = list(query.packs) if query.packs else enabled_pack_ids(conn)
    if not pack_ids:
        return LookupResult(Resolution((), "no_match", "no packs enabled"),
                            (), "NOT_MATCHED")

    resolution = resolve(conn, query, pack_ids)
    if not resolution.subject_ids:
        return LookupResult(resolution, (), "NOT_MATCHED")

    reached = expand(conn, resolution.subject_ids, pack_ids)
    tiers = tier_lookup(conn, pack_ids)
    trusts = trust_lookup(conn, pack_ids)
    weights = _pack_weights(conn)

    smarks = ",".join("?" * len(reached))
    pmarks = ",".join("?" * len(pack_ids))
    rows = conn.execute(
        f"SELECT c.*, s.label AS subject_label,"
        f"       COALESCE(t.title, '') AS title,"
        f"       COALESCE(t.body, '') AS body,"
        f"       COALESCE(t.advice, '') AS advice"
        f" FROM claims c"
        f" JOIN subjects s USING (subject_id, pack_id)"
        f" LEFT JOIN claim_text t"
        f"   ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id AND t.lang = ?"
        f" WHERE c.subject_id IN ({smarks}) AND c.pack_id IN ({pmarks})",
        (query.lang, *reached.keys(), *pack_ids))

    claims = []
    for row in rows:
        conditions = _conditions_for(conn, row["claim_id"], row["pack_id"])
        served, condition_weight, outcomes = evaluate_all(conditions, query.context)
        if not served:
            continue

        evidence = conn.execute(
            "SELECT e.quote, e.stance, e.independent, s.url, s.domain"
            " FROM evidence e JOIN sources s USING (source_id, pack_id)"
            " WHERE e.claim_id = ? AND e.pack_id = ?",
            (row["claim_id"], row["pack_id"])).fetchall()
        sources, trust, disputed = score_sources(evidence, tiers, trusts)

        via = reached.get(row["subject_id"], "direct")
        pack_weight = weights.get(row["pack_id"], 1.0)
        best_tier = max(sources, key=lambda s: s.trust).tier if sources else ""

        claims.append(Claim(
            claim_id=row["claim_id"], pack_id=row["pack_id"],
            subject_id=row["subject_id"], subject_label=row["subject_label"],
            kind=row["kind"], domain=row["domain"], severity=row["severity"],
            detection=row["detection"], title=row["title"], body=row["body"],
            advice=row["advice"],
            relevance=relevance(
                severity=row["severity"], condition_weight=condition_weight,
                detection=row["detection"], trust=trust, disputed=disputed,
                pack_weight=pack_weight),
            trust=trust, disputed=disputed, via=via,
            why=explain(
                severity=row["severity"], detection=row["detection"],
                trust=trust, tier=best_tier, disputed=disputed,
                condition_reasons=[o.reason for o in outcomes
                                   if o.state != "met"],
                via=via, pack_id=row["pack_id"]),
            sources=sources))

    # Sort by relevance, then severity, then title so the order is total and a
    # replay produces byte-identical output. Ties that resolve at random make
    # parity testing impossible.
    claims.sort(key=lambda c: (-c.relevance, c.severity, c.title))
    capped = tuple(claims[:query.limit])
    coverage = "RISKS_FOUND" if capped else "MATCHED_NO_DATA"
    return LookupResult(resolution, capped, coverage)
