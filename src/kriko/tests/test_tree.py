"""Reading the evidence back out — is what we ship actually well supported?

The fixtures here are built to exercise the four signals separately, because
the whole point of the ordering is that no signal is hidden inside a weighted
score. Two packs, because a cross-pack contradiction is the G6 case: two packs
may disagree and both must survive, ranked.
"""

import textwrap
from dataclasses import fields

import pytest

from kriko.lookup.tree import (UNKNOWN_STALENESS, ClaimHealth, health_json,
                               subject_tree, tree_json, weakest_claims)
from kriko.lookup.rank import tier_lookup, tier_of, trust_lookup
from kriko.pack import build
from kriko.store import ids, packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model_name, role: attribute, datatype: text, match: {required: true}}
- {term_id: mech, role: domain}
"""

TIERS = """
domains:
  maker.example.com: {tier: manufacturer}
  spec.example.net: {tier: specialist}
  forum.example.org: {tier: forum_ugc}
"""

ALPHA_TOML = """
[pack]
id = "alpha"
name = "Alpha"
version = "0.1.0"
[identity]
product = ["brand", "model_name"]
"""

ALPHA_SUBJECTS = """
- kind: product
  label: Widget 100
  identity: {brand: acme, model_name: w100}
"""

# Five claims, each weak in exactly one way, so an ordering bug shows up as a
# specific swap rather than as a vague reshuffle.
ALPHA_CLAIMS = """
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Refuted item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/a", quote: It fails., retrieved_at: "2026-08-01"}
    - {url: "https://spec.example.net/a", quote: It does not fail., stance: refutes, retrieved_at: "2026-08-01"}
    - {url: "https://forum.example.org/a", quote: Mine failed., retrieved_at: "2026-08-01"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Single forum item, body: b, advice: a}}
  evidence:
    - {url: "https://forum.example.org/b", quote: Happened to me., retrieved_at: "2026-08-01"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Single maker item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/c", quote: Service bulletin., retrieved_at: "2026-08-01"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Well sourced item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/d", quote: Bulletin., retrieved_at: "2026-08-02"}
    - {url: "https://spec.example.net/d", quote: Teardown., retrieved_at: "2026-08-02"}
    - {url: "https://forum.example.org/d", quote: Confirmed., retrieved_at: "2026-08-02"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: maintenance
  domain: mech
  severity: medium
  text: {en: {title: Unsourced maintenance item, body: b, advice: a}}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Older single maker item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/e", quote: Older bulletin., retrieved_at: "2026-01-01"}
"""

BETA_TOML = """
[pack]
id = "beta"
name = "Beta"
version = "0.1.0"
[identity]
product = ["brand", "model_name"]
"""

BETA_CLAIMS = """
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: low
  text: {en: {title: Beta item, body: b, advice: a}}
  evidence:
    - {url: "https://forum.example.org/z", quote: Beta saw it too., retrieved_at: "2026-07-01"}
"""


def _pack(tmp_path, name, *, toml, subjects, claims):
    root = tmp_path / name
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "trust").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(toml), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(subjects, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(claims, encoding="utf-8")
    (root / "trust" / "source_tiers.yaml").write_text(TIERS, encoding="utf-8")
    return build.build(root, tmp_path / f"{name}.kpack")


SUBJECT = ids.subject_id("product", {"brand": "acme", "model_name": "w100"})


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, _pack(tmp_path, "alpha", toml=ALPHA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=ALPHA_CLAIMS))
    yield conn
    conn.close()


@pytest.fixture
def two_packs(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, _pack(tmp_path, "alpha", toml=ALPHA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=ALPHA_CLAIMS))
    packstore.install(conn, _pack(tmp_path, "beta", toml=BETA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=BETA_CLAIMS))
    yield conn
    conn.close()


def _titles(rows):
    return [row.title for row in rows]


# ── the ordering ─────────────────────────────────────────────────────────

def test_a_refuted_claim_is_the_first_thing_on_the_list(store):
    """Shipping a claim while holding a rebuttal is the sharpest concern."""
    rows = weakest_claims(store)
    assert rows[0].title == "Refuted item"
    assert rows[0].refuted_by == 1


def test_a_refuted_claim_outranks_an_uncorroborated_one(store):
    """Three sources do not save it: contradiction is lexicographically first."""
    rows = weakest_claims(store)
    order = _titles(rows)
    assert order.index("Refuted item") < order.index("Single forum item")


def test_fewer_sources_ranks_above_more_sources(store):
    order = _titles(weakest_claims(store))
    assert order.index("Single maker item") < order.index("Well sourced item")


def test_a_weaker_best_source_ranks_above_a_stronger_one(store):
    """Same source count, so the tie breaks on the best tier's trust."""
    order = _titles(weakest_claims(store))
    assert order.index("Single forum item") < order.index("Single maker item")


def test_the_sort_key_is_inspectable_not_implicit(store):
    """`concern` is asserted directly — the order is a consequence, not the spec."""
    by_title = {row.title: row for row in weakest_claims(store)}
    assert by_title["Refuted item"].concern[0] == 0
    assert by_title["Single forum item"].concern[0] == 1
    assert by_title["Single forum item"].concern[1] == 1
    assert by_title["Well sourced item"].concern[1] == 3
    assert (by_title["Single forum item"].concern[2]
            < by_title["Single maker item"].concern[2])


def test_the_ordering_is_stable_across_calls(store):
    assert _titles(weakest_claims(store)) == _titles(weakest_claims(store))


def test_a_refuting_source_does_not_count_as_corroboration(store):
    """Three evidence rows, one refuting: two supporting sources, not three."""
    row = next(r for r in weakest_claims(store) if r.title == "Refuted item")
    assert row.supporting_sources == 2
    assert row.independent_sources == 2


def test_the_best_tier_ignores_the_refuting_source(store):
    """The rebuttal is specialist; the support is manufacturer and forum."""
    row = next(r for r in weakest_claims(store) if r.title == "Refuted item")
    assert row.best_tier == "manufacturer"


# ── absence is not weakness ──────────────────────────────────────────────

def test_a_claim_with_no_evidence_is_not_ranked_as_weak(store):
    """Absence is what coverage_gaps answers. rank.py treats it trust-neutral."""
    assert "Unsourced maintenance item" not in _titles(weakest_claims(store))


def test_a_claim_with_no_evidence_still_appears_in_its_subject_tree(store):
    tree = subject_tree(store, SUBJECT)
    node = next(n for n in tree.claims
                if n.health.title == "Unsourced maintenance item")
    assert node.evidence == ()


# ── unknown staleness is unknown, not stale ──────────────────────────────

def test_a_missing_retrieval_date_sorts_last_not_first(store, tmp_path):
    """An absent timestamp is not evidence of staleness.

    Today every one of the cars pack's 193 sources has an empty
    `retrieved_at`, so ranking blank as maximally stale would put the entire
    catalog at the top of the list on a signal carrying no information.
    """
    conn = store
    conn.execute("UPDATE sources SET retrieved_at = '' WHERE url LIKE '%/d'")
    conn.commit()
    row = next(r for r in weakest_claims(conn)
               if r.title == "Well sourced item")
    assert row.oldest_retrieved_at == ""
    assert row.concern[3] == UNKNOWN_STALENESS


def test_staleness_breaks_a_tie_when_everything_else_matches(store):
    """"Older single maker item" ties "Single maker item" on refuted-ness,
    independent source count and best trust (both: one manufacturer source);
    only the retrieval date differs, so the older one must rank first."""
    order = _titles(weakest_claims(store))
    assert order.index("Older single maker item") < order.index("Single maker item")

    by_title = {row.title: row for row in weakest_claims(store)}
    older = by_title["Older single maker item"].concern
    newer = by_title["Single maker item"].concern
    assert older[:3] == newer[:3]
    assert older[3] < newer[3]


# ── two packs ────────────────────────────────────────────────────────────

def test_the_list_unions_across_enabled_packs(two_packs):
    rows = weakest_claims(two_packs)
    assert {"alpha", "beta"} <= {row.pack_id for row in rows}


def test_a_subject_tree_reports_every_pack_that_speaks_to_it(two_packs):
    tree = subject_tree(two_packs, SUBJECT)
    assert set(tree.pack_ids) == {"alpha", "beta"}
    assert "Beta item" in [node.health.title for node in tree.claims]


def test_a_disabled_pack_disappears_from_the_list(two_packs):
    packstore.set_enabled(two_packs, "beta", False)
    rows = weakest_claims(two_packs)
    assert "beta" not in {row.pack_id for row in rows}


def test_an_explicit_pack_id_list_narrows_the_query(two_packs):
    rows = weakest_claims(two_packs, ["alpha"])
    assert {row.pack_id for row in rows} == {"alpha"}


# ── empty and missing ────────────────────────────────────────────────────

def test_an_empty_store_returns_an_empty_list_not_an_error(tmp_path):
    conn = connect(tmp_path / "empty.sqlite")
    assert weakest_claims(conn) == []
    conn.close()


def test_an_unknown_subject_returns_an_empty_tree_not_an_error(store):
    tree = subject_tree(store, "no-such-subject")
    assert tree.claims == ()
    assert tree.label == ""


def test_the_limit_is_honoured(store):
    assert len(weakest_claims(store, limit=2)) == 2


# ── one tier-resolution path, not two ────────────────────────────────────

def test_the_tree_and_rank_agree_on_every_tier(store):
    """A second tier-resolution path is exactly the duplication two earlier
    passes existed to delete. This asserts there is only one."""
    tiers = tier_lookup(store, ["alpha"])
    trusts = trust_lookup(store, ["alpha"])
    tree = subject_tree(store, SUBJECT)
    seen = 0
    for node in tree.claims:
        for row in node.evidence:
            expected = tier_of(row.domain, tiers)
            assert row.tier == expected
            assert row.trust == trusts[expected]
            seen += 1
    assert seen > 0


# ── JSON helpers ─────────────────────────────────────────────────────────

def test_health_json_carries_concern_alongside_every_field(store):
    health = weakest_claims(store)[0]
    payload = health_json(health)
    assert payload["concern"] == list(health.concern)
    for field in fields(ClaimHealth):
        assert field.name in payload


def test_tree_json_carries_health_and_evidence_per_claim(store):
    tree = subject_tree(store, SUBJECT)
    payload = tree_json(tree)
    first = payload["claims"][0]
    assert "health" in first
    assert "evidence" in first
