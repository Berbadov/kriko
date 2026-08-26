"""Read-time ranking — where "no authority" is actually cashed out.

The old pipeline stamped `source_tier` and `source_trust` onto each claim row at
ETL time, which froze a judgement made once, by one pipeline, and made it
unrevisable. Here trust is computed on every read from the evidence itself, so
installing a better source-tier table or disabling a pack changes the answer
without rebuilding anything.

This matters more than it sounds. With no central authority, ranking *is* the
product: every installed pack gets to assert whatever it likes, and the only
thing standing between the reader and a pile of contradictory noise is the order
things come back in. So each factor here is deliberately explainable — every
score carries the reasons that produced it, and the UI can show them.
"""

from kriko.lookup.query import Source

# Severity is the dominant term, as in the serving path today.
SEVERITY_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}

# Default trust per tier. A pack may ship its own `tier_trust` rows; the
# reader's local rows win over both. These are the fallback, not a policy.
DEFAULT_TIER_TRUST = {
    "authoritative": 1.0,
    "manufacturer": 1.0,
    "specialist": 0.8,
    "editorial": 0.7,
    "forum_ugc": 0.45,
    "seo_blog": 0.3,
    "unknown": 0.5,
}

# A claim only a camera can catch is worth less to a buyer than one a test drive
# reveals — carried over from resolver.VISUAL_DETECTION_FACTOR.
VISUAL_DETECTION_FACTOR = 0.35

# Corroboration is capped: the fifth independent source says much less than the
# second, and an uncapped count would let a spammy pack outrank a manufacturer.
MAX_CORROBORATION = 1.3
CORROBORATION_STEP = 0.15

# A contradicted claim still surfaces — hiding it would be an authority decision
# — but it must not sit at the top while a rebuttal exists.
DISPUTE_FACTOR = 0.5


def tier_lookup(conn, pack_ids) -> dict[str, str]:
    """domain -> tier, unioned across enabled packs, with local rows winning."""
    if not pack_ids:
        return {}
    marks = ",".join("?" * len(pack_ids))
    tiers: dict[str, str] = {}
    for row in conn.execute(
            f"SELECT domain_pattern, tier, pack_id FROM source_tiers"
            f" WHERE pack_id IN ({marks}) OR pack_id = 'local'"
            f" ORDER BY CASE WHEN pack_id = 'local' THEN 1 ELSE 0 END",
            tuple(pack_ids)):
        tiers[row["domain_pattern"].casefold()] = row["tier"]
    return tiers


def trust_lookup(conn, pack_ids) -> dict[str, float]:
    weights = dict(DEFAULT_TIER_TRUST)
    if pack_ids:
        marks = ",".join("?" * len(pack_ids))
        for row in conn.execute(
                f"SELECT tier, trust FROM tier_trust"
                f" WHERE pack_id IN ({marks}) OR pack_id = 'local'", tuple(pack_ids)):
            weights[row["tier"]] = float(row["trust"])
    return weights


def tier_of(domain: str, tiers: dict[str, str]) -> str:
    """Resolve a domain to a tier, most specific rule first.

    Four steps, in order: the exact domain, then each parent domain so one row
    covers every subdomain, then `*substring*` contains-rules (which is how a
    pack says "anything with 'forum.' in it is user-generated" without listing
    the internet), then the pack's `*` default. Falling through all four gives
    `unknown`, which is trust-neutral rather than a penalty — an unrecognised
    domain is not evidence of a bad source.
    """
    domain = (domain or "").casefold()
    if not domain:
        return "unknown"
    if domain in tiers:
        return tiers[domain]

    parts = domain.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[i:])
        if parent in tiers:
            return tiers[parent]

    for pattern, tier in tiers.items():
        if pattern.startswith("*") and pattern.endswith("*") and len(pattern) > 2:
            if pattern[1:-1] in domain:
                return tier

    return tiers.get("*", "unknown")


def score_sources(rows, tiers, trusts) -> tuple[tuple[Source, ...], float, bool]:
    """Turn evidence rows into sources, a trust score, and a disputed flag.

    Trust is the *best* supporting source, not the average: one manufacturer
    bulletin is worth more than five forum posts, and averaging would let noise
    drag down a well-sourced claim.
    """
    sources = []
    best = 0.0
    disputed = False
    independent = 0

    for row in rows:
        tier = tier_of(row["domain"], tiers)
        trust = trusts.get(tier, DEFAULT_TIER_TRUST["unknown"])
        stance = row["stance"]
        sources.append(Source(url=row["url"], domain=row["domain"],
                              quote=row["quote"], stance=stance,
                              tier=tier, trust=trust))
        if stance == "refutes":
            disputed = True
            continue
        best = max(best, trust)
        if row["independent"]:
            independent += 1

    if not sources:
        # Maintenance claims carry no sources by nature. Trust-neutral, never
        # penalised — a due cam belt is not less true for lacking a citation.
        return (), 1.0, False

    corroboration = min(
        MAX_CORROBORATION, 1 + CORROBORATION_STEP * max(0, independent - 1))
    return tuple(sources), best * corroboration, disputed


def relevance(*, severity: str, condition_weight: float, detection: str,
              trust: float, disputed: bool, pack_weight: float,
              author_confidence: float | None = None) -> float:
    """Combine every factor into one comparable number.

    `author_confidence` is where the old `status` column ended up. With no
    authority there is nobody to "promote" a claim from review to verified, so
    review state becomes rank rather than a gate: an unreviewed claim still
    reaches the reader, ranked below a corroborated one. Dropping status
    outright would have shipped the catalog's 696 unreviewed claims as
    first-class (backlog B26); treating it as a hide would have been an
    authority decision by another name.
    """
    score = SEVERITY_WEIGHT.get(severity, 0.5)
    score *= condition_weight
    if author_confidence is not None:
        score *= author_confidence
    if detection == "visual":
        score *= VISUAL_DETECTION_FACTOR
    score *= trust or 1.0
    if disputed:
        score *= DISPUTE_FACTOR
    return score * pack_weight


def explain(*, severity, detection, trust, tier, disputed, condition_reasons,
            via, pack_id) -> tuple[str, ...]:
    """Every reason this claim scored what it did, in the reader's language."""
    why = [f"{severity} severity"]
    if via and via != "direct":
        kind = via.split(":", 1)[0]
        why.append(f"applies through the {kind.replace('_', ' ')} it shares")
    if tier and tier != "unknown":
        why.append(f"best source is {tier} (trust {trust:.2f})")
    if detection == "visual":
        why.append("only visible on inspection — ranked down")
    if disputed:
        why.append("contradicted by another source — ranked down, rebuttal shown")
    why.extend(condition_reasons)
    why.append(f"from pack: {pack_id}")
    return tuple(why)
