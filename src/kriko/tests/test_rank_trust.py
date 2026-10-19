"""Trust is a multiplier, so a zero has to stay a zero.

Two defects from the 2026-10-18 sweep, both in the one place this engine cashes
out "no authority":

* `relevance` wrote `score *= trust or 1.0`, which cannot tell *unknown* trust
  (`None`) from *no* trust (`0.0`). `score_sources` returns 0.0 for a claim whose
  every cited source refutes it, so the most thoroughly contradicted claim in a
  catalog was ranked as if its trust were simply unrecorded.
* `trust_lookup` had no `ORDER BY`, so the module's own promise — "the reader's
  local rows win over both" — was whichever row the planner happened to return
  last. `tier_lookup`, three lines above it, states the precedence in SQL.
"""

import sqlite3

from kriko.lookup.rank import relevance, score_sources, trust_lookup

#: Everything `relevance` needs except trust: a high-severity, documented claim
#: that is disputed by one of its own sources.
_BASE = {
    "severity": "high",
    "condition_weight": 1.0,
    "detection": "documented",
    "pack_weight": 1.0,
    "author_confidence": None,
    "disputed": True,
}


def _evidence(stance, source_id="s1", domain="example.invalid"):
    return {
        "source_id": source_id,
        "stance": stance,
        "independent": 1,
        "domain": domain,
        "url": "https://example.invalid/teardown",
        "quote": "Packs past roughly five hundred cycles showed a 0.4 V spread.",
    }


def test_a_claim_whose_only_evidence_refutes_it_earns_no_trust():
    """`best` never leaves its initial 0.0 when every row is counter-evidence."""
    _sources, trust, disputed = score_sources([_evidence("refutes")], {}, {})
    assert trust == 0.0
    assert disputed is True


def test_a_contradicted_claim_is_not_ranked_as_a_trusted_one():
    """The bug, stated as a score: 0.0 trust must not multiply by 1.0.

    Before the fix this returned 0.5 — the same score as a claim whose trust is
    merely unrecorded — because `0.0 or 1.0` is `1.0`.
    """
    _sources, trust, _disputed = score_sources([_evidence("refutes")], {}, {})
    assert relevance(trust=trust, **_BASE) == 0.0


def test_an_unknown_trust_still_falls_back_to_neutral():
    """`None` is not zero, and must keep the trust-neutral reading."""
    assert relevance(trust=None, **_BASE) == 0.5


def test_a_claim_with_no_sources_is_trust_neutral_not_damned():
    """A due cam belt is not less true for lacking a citation."""
    assert score_sources([], {}, {})[1] == 1.0


def test_a_supported_claim_keeps_the_best_of_its_sources():
    _sources, trust, _disputed = score_sources(
        [_evidence("supports", source_id="a"), _evidence("refutes", source_id="b")], {}, {})
    assert trust == 0.5          # the per-tier default for `unknown`
    assert relevance(trust=trust, **_BASE) == 0.25


def _tier_weights(rows):
    """`trust_lookup` over a `tier_trust` table holding exactly `rows`."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tier_trust (pack_id TEXT, tier TEXT, trust REAL)")
    conn.executemany("INSERT INTO tier_trust VALUES (?,?,?)",
                     [(pack_id, "seo_blog", trust) for pack_id, trust in rows])
    return trust_lookup(conn, ["some.pack"])["seo_blog"]


def test_the_readers_own_weight_wins_whichever_row_was_inserted_last():
    """Scan order is not precedence; `local` is."""
    assert _tier_weights([("some.pack", 0.9), ("local", 0.1)]) == 0.1
    assert _tier_weights([("local", 0.1), ("some.pack", 0.9)]) == 0.1


def test_a_pack_weight_still_applies_where_the_reader_declared_none():
    assert _tier_weights([("some.pack", 0.9)]) == 0.9
