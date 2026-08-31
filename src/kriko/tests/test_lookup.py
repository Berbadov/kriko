"""End-to-end lookup: an identity dict in, ranked claims out.

This is the generic replacement for `matcher.py` (226 lines) plus `resolver.py`
(650 lines). Everything those two knew about cars now arrives as pack data.

The fixtures here are deliberately *two* packs that disagree, because the two
properties that make the pivot work are only visible with more than one pack
installed: subjects that hash differently must still meet, and claims that
contradict must both survive.
"""

import textwrap

import pytest

from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: component, role: subject_kind}
- {term_id: part_of, role: predicate}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}, aliases: [make]}
- {term_id: model, role: attribute, datatype: text, match: {required: true}}
- {term_id: trim, role: attribute, datatype: text}
- {term_id: power_hp, role: attribute, datatype: number, unit: hp, match: {narrow_order: 1, tolerance: 5}}
- {term_id: part, role: attribute, datatype: text}
- {term_id: usage_km, role: context_key, datatype: number, unit: km}
- {term_id: mech, role: domain}
"""


# A pack ships its own view of which domains are trustworthy. The engine holds
# only fallback weights per tier, so trust is revisable by installing data.
TIERS = """
domains:
  maker.example.com: {tier: manufacturer}
  forum.example.org: {tier: forum_ugc}
"""


def _pack(tmp_path, name, *, toml, subjects, claims, terms=TERMS, tiers=TIERS):
    root = tmp_path / name
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "trust").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(toml), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(terms, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(subjects, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(claims, encoding="utf-8")
    (root / "trust" / "source_tiers.yaml").write_text(tiers, encoding="utf-8")
    return build.build(root, tmp_path / f"{name}.kpack")


ALPHA_TOML = """
[pack]
id = "alpha"
name = "Alpha"
version = "0.1.0"
[identity]
product = ["brand", "model"]
component = ["part"]
"""

ALPHA_SUBJECTS = """
- kind: component
  label: Timing chain
  identity: {part: timing_chain}
- kind: product
  label: Widget 100
  identity: {brand: acme, model: w100}
  attributes: {power_hp: 100}
  relations:
    - {predicate: part_of, object: {kind: component, identity: {part: timing_chain}}}
- kind: product
  label: Widget 150
  identity: {brand: acme, model: w150}
  attributes: {power_hp: 150}
"""

ALPHA_CLAIMS = """
- subject: {kind: component, identity: {part: timing_chain}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Chain tensioner fails, body: b, advice: a}}
  conditions:
    - {key: usage_km, op: gte, value: 120000, on_missing: open, weight: 0.7}
  evidence:
    - {url: "https://maker.example.com/tsb/1", quote: Tensioner replaced under warranty.}
- subject: {kind: product, identity: {brand: acme, model: w100}}
  kind: known_issue
  domain: mech
  severity: low
  text: {en: {title: Trim rattle, body: b, advice: a}}
  evidence:
    - {url: "https://forum.example.org/t/9", quote: Mine rattles over bumps.}
"""


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, _pack(tmp_path, "alpha", toml=ALPHA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=ALPHA_CLAIMS))
    yield conn
    conn.close()


def _titles(result):
    return [c.title for c in result.claims]


# ── resolving an identity to subjects ────────────────────────────────────

def test_exact_identity_resolves_to_one_subject(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"}))
    assert result.resolution.method == "exact"
    assert len(result.resolution.subject_ids) == 1


def test_an_alias_resolves_to_its_term(store):
    """'make' is a car word. Here it is just an alias row, resolved as data."""
    result = lookup(store, Query(kind="product",
                                 identity={"make": "acme", "model": "w100"}))
    assert result.resolution.method == "exact"


def test_identity_matching_is_case_insensitive(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "ACME", "model": "W100"}))
    assert result.resolution.method == "exact"


def test_an_unknown_product_is_no_match_not_an_error(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "nope"}))
    assert result.resolution.method == "no_match"
    assert result.coverage == "NOT_MATCHED"
    assert result.claims == ()


def test_a_partial_identity_matches_several_subjects(store):
    result = lookup(store, Query(kind="product", identity={"brand": "acme"}))
    assert result.resolution.method == "ambiguous"
    assert len(result.resolution.subject_ids) == 2


def test_a_numeric_hint_narrows_an_ambiguous_match(store):
    """power_hp has a tolerance of 5, so 148 picks the 150 and not the 100."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "power_hp": 148}))
    assert result.resolution.method == "exact"


def test_narrowing_is_soft_and_never_empties_the_candidates(store):
    """A hint that matches nothing must not turn a real match into no_match."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "power_hp": 9999}))
    assert result.resolution.method == "ambiguous"
    assert "power_hp" in " ".join(result.resolution.flags)


def test_a_contradiction_is_still_flagged_when_only_one_candidate_is_left(store):
    """The single-candidate case is where a silent contradiction does most harm.

    History: narrowing used to be skipped once the candidate set was down to
    one, on the reasoning that there was nothing left to narrow — but that
    left the contradicting attribute untested, so no flag was raised and the
    result came back `exact` with no indication that the listing disagreed
    with the catalog.

    A real case, found on the cars pack: a listing named a hint value the
    catalog had no matching row for, but the other identity fields still
    narrowed to exactly one variant anyway. That hint attribute then went
    untested, so the buyer was told `exact`, shown no claims that depended
    on it, and nothing anywhere recorded that what they were looking at is
    missing from the catalog. Exactly the quiet zero goal G3 exists to
    prevent.

    Confidence must not be an artefact of having stopped checking.
    """
    result = lookup(store, Query(
        kind="product",
        identity={"brand": "acme", "model": "w100", "power_hp": 9999}))

    assert result.resolution.subject_ids, "the product must still resolve — a contradiction is a flag, not a rejection"
    assert "power_hp" in " ".join(result.resolution.flags), (
        "the contradicting attribute must be flagged even though there was only "
        "one candidate to contradict"
    )


# ── reaching claims through relations ────────────────────────────────────

def test_a_component_claim_reaches_the_product_that_uses_it(store):
    """The traversal that lets an engine-code claim reach every car fitted with it."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"},
                                 context={"usage_km": 200_000}))
    assert "Chain tensioner fails" in _titles(result)


def test_a_product_without_that_component_does_not_get_the_claim(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w150"},
                                 context={"usage_km": 200_000}))
    assert "Chain tensioner fails" not in _titles(result)


def test_a_product_with_no_relations_still_returns_its_own_claims(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w150"}))
    assert result.coverage == "MATCHED_NO_DATA"


# ── conditions ───────────────────────────────────────────────────────────

def test_a_mileage_gated_claim_is_withheld_below_the_threshold(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"},
                                 context={"usage_km": 10_000}))
    assert "Chain tensioner fails" not in _titles(result)


def test_an_unstated_mileage_still_shows_the_claim_but_downranked(store):
    """Unknown is not false. Losing this is how a buyer misses a real risk."""
    with_km = lookup(store, Query(kind="product",
                                  identity={"brand": "acme", "model": "w100"},
                                  context={"usage_km": 200_000}))
    without = lookup(store, Query(kind="product",
                                  identity={"brand": "acme", "model": "w100"}))

    assert "Chain tensioner fails" in _titles(without)
    scored = {c.title: c.relevance for c in with_km.claims}
    unscored = {c.title: c.relevance for c in without.claims}
    assert unscored["Chain tensioner fails"] < scored["Chain tensioner fails"]


def test_why_shown_explains_a_downrank(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"}))
    claim = next(c for c in result.claims if c.title == "Chain tensioner fails")
    assert "usage_km" in " ".join(claim.why)


# ── ranking ──────────────────────────────────────────────────────────────

def test_severity_orders_the_results(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"},
                                 context={"usage_km": 200_000}))
    assert _titles(result)[0] == "Chain tensioner fails"


def test_source_tier_lifts_an_authoritative_claim_over_a_forum_one(store):
    """Trust is computed at read time from the evidence, not frozen at ETL."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"},
                                 context={"usage_km": 200_000}))
    by_title = {c.title: c for c in result.claims}
    assert by_title["Chain tensioner fails"].trust > by_title["Trim rattle"].trust


def test_the_result_is_capped(store):
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"},
                                 context={"usage_km": 200_000}, limit=1))
    assert len(result.claims) == 1


def test_every_claim_names_the_pack_it_came_from(store):
    """With no authority, attribution is the reader's only defence."""
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"},
                                 context={"usage_km": 200_000}))
    assert all(c.pack_id == "alpha" for c in result.claims)


def test_a_disabled_pack_contributes_nothing(store):
    packstore.set_enabled(store, "alpha", False)
    result = lookup(store, Query(kind="product",
                                 identity={"brand": "acme", "model": "w100"}))
    assert result.resolution.method == "no_match"


# ── cross-pack union ─────────────────────────────────────────────────────
#
# The riskiest property in the whole design. Two authors who disagree about what
# makes a product distinct hash it to different subject_ids, so their rows never
# meet in storage. If lookup keyed on subject_id equality, installing both packs
# would give you two half-answers instead of one whole one — and "install the
# packs you need" would quietly not work.
#
# Matching on attribute overlap is what saves it: both subjects satisfy
# brand=acme + model=w100, so both survive the hard filter and their claims
# union. No coordination between authors, and no central registry.

BETA_TOML = """
[pack]
id = "beta"
name = "Beta"
version = "0.1.0"
[identity]
product = ["brand", "model", "trim"]
"""

BETA_SUBJECTS = """
- kind: product
  label: Widget 100 GT
  identity: {brand: acme, model: w100, trim: gt}
  attributes: {power_hp: 100}
"""

BETA_CLAIMS = """
- subject: {kind: product, identity: {brand: acme, model: w100, trim: gt}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Bearing whine, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/tsb/7", quote: Bearing revised in later builds.}
"""


@pytest.fixture
def two_packs(store, tmp_path):
    packstore.install(store, _pack(tmp_path, "beta", toml=BETA_TOML,
                                   subjects=BETA_SUBJECTS, claims=BETA_CLAIMS))
    return store


def test_packs_that_disagree_on_identity_keys_still_both_answer(two_packs):
    """Alpha hashes the product on brand+model; beta adds trim. Both must count."""
    result = lookup(two_packs, Query(kind="product",
                                     identity={"brand": "acme", "model": "w100"},
                                     context={"usage_km": 200_000}))
    assert {c.pack_id for c in result.claims} == {"alpha", "beta"}
    assert "Bearing whine" in _titles(result)
    assert "Chain tensioner fails" in _titles(result)


def test_the_two_subjects_really_did_hash_differently(two_packs):
    """Guards the test above from passing for the wrong reason."""
    rows = two_packs.execute(
        "SELECT DISTINCT subject_id, pack_id FROM attributes"
        " WHERE key = 'model' AND value_text = 'w100'").fetchall()
    assert len({r["pack_id"] for r in rows}) == 2
    assert len({r["subject_id"] for r in rows}) == 2


def test_uninstalling_one_pack_leaves_the_other_answering(two_packs):
    packstore.uninstall(two_packs, "beta")
    result = lookup(two_packs, Query(kind="product",
                                     identity={"brand": "acme", "model": "w100"},
                                     context={"usage_km": 200_000}))
    assert {c.pack_id for c in result.claims} == {"alpha"}
    assert "Chain tensioner fails" in _titles(result)
