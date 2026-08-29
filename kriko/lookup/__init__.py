"""One lookup path, for every product category and every caller.

    identity + context  ->  subjects  ->  claims  ->  gated  ->  ranked  ->  capped

This replaces `backend/core/matcher.py` and `backend/core/resolver.py`, which
together held 876 lines of car packs.cars.pipeline. Nothing here knows what a car is; the
rules arrive as pack rows. The proof is mechanical rather than aspirational:
`test_kriko_core_never_imports_a_domain_layer` forbids this package from
importing `packs/`, and the drill pack's suite runs the same code path over
charge cycles and chuck sizes.
"""

from dataclasses import replace

from kriko.lookup.conditions import Condition, evaluate_all
from kriko.lookup.match import expand, resolve
from kriko.lookup.query import Claim, LookupResult, Query, Resolution
from kriko.lookup.rank import explain, relevance, score_sources, tier_lookup, trust_lookup
from kriko.store.packstore import enabled_pack_ids
from kriko.text.title_sim import cluster

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


def _subject_pack(conn, subject_id: str) -> str:
    row = conn.execute("SELECT pack_id FROM subjects WHERE subject_id = ?",
                       (subject_id,)).fetchone()
    return row["pack_id"] if row else ""


def _agreed_attributes(conn, subject_ids, pack_ids) -> dict:
    """What the catalog says about the matched thing, where the candidates agree.

    Conditions are evaluated against the union of this and the reader's context,
    because "does this claim apply" depends on both what the catalog knows (this
    car is a diesel) and what the reader supplied (it has done 180,000 km).

    Only *agreed* values are included. If two candidate subjects disagree — one
    diesel, one petrol — the key is omitted, which makes the condition
    `unknown` and therefore fail open. That is the right answer: with the
    candidates in disagreement we genuinely do not know, and guessing either way
    would either hide a real risk or invent one.
    """
    if not subject_ids or not pack_ids:
        return {}
    smarks = ",".join("?" * len(subject_ids))
    pmarks = ",".join("?" * len(pack_ids))
    seen: dict[str, set] = {}
    for row in conn.execute(
            f"SELECT key, value_text FROM attributes"
            f" WHERE subject_id IN ({smarks}) AND pack_id IN ({pmarks})",
            (*subject_ids, *pack_ids)):
        seen.setdefault(row["key"], set()).add(row["value_text"])
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _merge_cluster(group: list) -> "Claim":
    """Keep the best-ranked claim, absorbing the others' sources as corroboration.

    The duplicates are not discarded silently — their evidence joins the
    survivor, because three packs describing one failure in three ways is three
    sources for it, and that is exactly the signal corroboration should reward.
    """
    best = group[0]
    if len(group) == 1:
        return best

    seen = {(s.url, s.quote) for s in best.sources}
    extra = tuple(s for other in group[1:] for s in other.sources
                  if (s.url, s.quote) not in seen)
    others = sorted({c.pack_id for c in group[1:]} - {best.pack_id})
    why = best.why + ((f"also reported by: {', '.join(others)}",) if others else ())

    return replace(best, sources=best.sources + extra, why=why)


def lookup(conn, query: Query) -> LookupResult:
    pack_ids = list(query.packs) if query.packs else enabled_pack_ids(conn)
    if not pack_ids:
        return LookupResult(Resolution((), "no_match", "no packs enabled"),
                            (), "NOT_MATCHED")

    resolution = resolve(conn, query, pack_ids)
    if not resolution.subject_ids:
        return LookupResult(resolution, (), "NOT_MATCHED")

    # Ambiguity is resolved WITHIN a pack, never across packs.
    #
    # Within one pack, two matching subjects mean the catalog cannot tell which
    # variant this listing is, so serve only what holds for both. Telling a
    # buyer about a gearbox belonging to one of two candidates is worse than
    # saying less — the claim is not wrong, it is unattributable, and an
    # unattributable claim about an expensive part is the noise that makes
    # people stop reading.
    #
    # Across packs it is the opposite: two packs matching the same car is not
    # ambiguity, it is two answers to one question, and intersecting them would
    # mean installing a second pack could only ever *reduce* what you see.
    reached = {}
    for pack_id in pack_ids:
        in_pack = [sid for sid in resolution.subject_ids
                   if _subject_pack(conn, sid) == pack_id]
        if not in_pack:
            continue
        expansions = [expand(conn, (sid,), (pack_id,)) for sid in in_pack]
        common = set.intersection(*(set(e) | {sid}
                                    for e, sid in zip(expansions, in_pack)))
        for sid in common:
            # Keep the route expand() reported — it is what `why` shows the
            # reader ("applies through the part it shares").
            via = next((e[sid] for e in expansions if sid in e), "direct")
            if sid not in resolution.subject_ids and len(in_pack) > 1:
                via = "shared_by_all_candidates"
            reached.setdefault(sid, via)

    if not reached:
        return LookupResult(resolution, (), "MATCHED_NO_DATA")
    # The reader's own words win over the catalog's generic row: if the ad says
    # the gearbox is automatic, that beats what the catalog assumed.
    context = {**_agreed_attributes(conn, resolution.subject_ids, pack_ids),
               **query.context}

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
        served, condition_weight, outcomes = evaluate_all(conditions, context)
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
                pack_weight=pack_weight,
                author_confidence=row["author_confidence"]),
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

    # Then collapse near-duplicates. This is where the reader's experience of
    # "no authority" is made bearable: several packs, and several passes of one
    # pipeline, describe the same failure in different words, and showing all of
    # them would bury the four things that matter under twelve rewordings of one.
    # Sorted best-first above, so each cluster's representative is already the
    # highest-ranked member and the rest fold into it as corroboration.
    clusters = cluster(claims, key=lambda c: c.title,
                       group=lambda c: c.domain)
    deduped = [_merge_cluster(group) for group in clusters]
    deduped.sort(key=lambda c: (-c.relevance, c.severity, c.title))
    capped = tuple(deduped[:query.limit])
    coverage = "RISKS_FOUND" if capped else "MATCHED_NO_DATA"
    return LookupResult(resolution, capped, coverage)
