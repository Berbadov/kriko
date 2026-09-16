"""Near-matching: the reader built a pack and the extension did not see it.

Every test here is a listing that a real catalog would fail to recognise for a
reason that has nothing to do with whether the pack covers the product. The
exact path returns `no_match` for all of them, which is how a good pack became
invisible on the one page it was written for.

The fixture is the same two-pack shape `test_lookup.py` uses, because the
property that matters most — a pack's thresholds are its own — is only visible
with a second pack installed that disagrees about them.
"""

import textwrap

import pytest

from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.lookup.score import _closeness, thresholds
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model, role: attribute, datatype: text, match: {required: true}}
- {term_id: engine, role: attribute, datatype: text}
- {term_id: mech, role: domain}
"""

TOML = """
[pack]
id = "motors"
name = "Motors"
version = "0.1.0"
[identity]
product = ["brand", "model", "engine"]
"""

SUBJECTS = """
- kind: product
  label: Volkswagen Golf 1.6 TDI
  identity: {brand: volkswagen, model: golf, engine: "1.6 tdi"}
- kind: product
  label: Volkswagen Passat 2.0 TDI
  identity: {brand: volkswagen, model: passat, engine: "2.0 tdi"}
"""

CLAIMS = """
- subject: {kind: product, identity: {brand: volkswagen, model: golf, engine: "1.6 tdi"}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Timing belt due as a kit, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/tsb/1", quote: Replace the belt with the pump.}
"""


def _build(tmp_path, name, *, gates=""):
    root = tmp_path / name
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "pack.toml").write_text(
        textwrap.dedent(TOML).replace('id = "motors"', f'id = "{name}"'),
        encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    if gates:
        (root / "vocabulary" / "gates.yaml").write_text(gates, encoding="utf-8")
    return build.build(root, tmp_path / f"{name}.kpack")


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, _build(tmp_path, "motors"))
    yield conn
    conn.close()


def _ask(store, **identity):
    return lookup(store, Query(kind="product", identity=identity))


# ── the reported bug ─────────────────────────────────────────────────────

def test_a_listing_more_specific_than_the_catalog_is_still_recognised(store):
    """The page says `1.6 TDI CR`; the catalog says `1.6 TDI`.

    Byte-unequal, same engine. Before scoring this was `no_match` and the whole
    pack vanished from the panel — the exact defect the reader reported.
    """
    result = _ask(store, brand="volkswagen", model="golf", engine="1.6 TDI CR")
    assert result.resolution.method in {"exact", "ambiguous"}
    assert result.resolution.score < 1.0, "matched by score, not by luck"
    assert [c.title for c in result.claims] == ["Timing belt due as a kit"]


def test_an_abbreviated_maker_still_finds_the_pack(store):
    """`VW` is not a declared alias here, and must not cost the reader the pack.

    A pack *should* declare it — `term_aliases` is the right home for a real
    abbreviation. This is the safety net for the ones nobody thought of, which
    is all of them on the day a pack is first written.
    """
    result = _ask(store, brand="VW", model="golf", engine="1.6 tdi")
    assert result.resolution.method != "no_match"
    assert result.claims


def test_a_listing_less_specific_than_the_catalog_is_recognised(store):
    result = _ask(store, brand="Volkswagen", model="Golf", engine="1.6 TDI")
    assert result.resolution.method == "exact"


# ── and the thing it must not do ─────────────────────────────────────────

def test_a_contradicted_key_is_not_a_probable_match(store):
    """A model that flatly disagrees is evidence *against*, not a missing key.

    Without the conflict penalty this scores 0.5 — brand right, model wrong,
    engine absent — and the reader is confidently offered the wrong car. That
    is worse than the blank page scoring was added to fix.
    """
    result = _ask(store, brand="volkswagen", model="tiguan")
    assert result.resolution.method == "no_match"
    assert result.claims == ()


def test_a_different_product_entirely_is_still_no_match(store):
    result = _ask(store, brand="makita", model="dhp484")
    assert result.resolution.method == "no_match"
    assert result.coverage == "NOT_MATCHED"


# ── what the reader is told instead of nothing ───────────────────────────

def test_no_match_says_what_the_nearest_thing_was(store):
    """A dead end is the bug. The note names the closest subject and its score."""
    result = _ask(store, brand="volkswagen", model="tiguan")
    assert "nearest" in result.resolution.notes
    assert result.resolution.considered, "nothing to show the reader or a dev"


def test_every_candidate_weighed_is_carried_back_with_its_reasons(store):
    result = _ask(store, brand="volkswagen", model="tiguan")
    best = result.resolution.considered[0]
    assert best.label
    assert any("against" in why for why in best.why), best.why
    assert {one.how for one in best.per_key} <= {
        "exact", "similar", "conflict", "absent"}


def test_a_probable_match_is_labelled_rather_than_served_as_certain(store):
    """Between the two thresholds: served, and marked as a question.

    `brand` and `engine` agree and `model` disagrees — a listing whose title
    names a different model from the one its engine and maker point at, which
    is what a mis-parsed page looks like. Too weak to assume and too strong to
    bin, which is exactly what the middle band is for: the reader gets the
    claims *and* the doubt.
    """
    result = _ask(store, brand="volkswagen", model="tiguan", engine="1.6 tdi")
    assert result.resolution.method == "probable"
    assert result.coverage == "PROBABLE_MATCH"
    assert result.claims, "a probable match still shows what it would say"


# ── the thresholds belong to the pack ────────────────────────────────────

def test_a_pack_declares_its_own_thresholds(tmp_path):
    conn = connect(tmp_path / "strict.sqlite")
    packstore.install(conn, _build(tmp_path, "strict", gates="""
limits:
  - {pattern: match_floor, note: "0.95"}
  - {pattern: match_probable, note: "0.9"}
"""))
    assert thresholds(conn, "strict") == (0.95, 0.9)
    # Same listing as the first test, against a pack that wants near-certainty.
    result = lookup(conn, Query(kind="product", identity={
        "brand": "volkswagen", "model": "golf", "engine": "1.6 TDI CR"}))
    assert result.resolution.method != "exact"
    conn.close()


def test_an_undeclared_pack_gets_the_engine_defaults(store):
    from kriko.lookup.score import DEFAULT_FLOOR, DEFAULT_PROBABLE

    assert thresholds(store, "motors") == (DEFAULT_FLOOR, DEFAULT_PROBABLE)


def test_a_nonsense_threshold_does_not_make_a_pack_unmatchable(tmp_path):
    """A typo in one row must cost a little precision, never the whole pack."""
    conn = connect(tmp_path / "typo.sqlite")
    packstore.install(conn, _build(tmp_path, "typo", gates="""
limits:
  - {pattern: match_floor, note: "very strict"}
  - {pattern: match_probable, note: "40"}
"""))
    from kriko.lookup.score import DEFAULT_FLOOR

    floor, probable = thresholds(conn, "typo")
    assert floor == DEFAULT_FLOOR
    assert probable <= floor
    conn.close()


# ── the measure itself ───────────────────────────────────────────────────

@pytest.mark.parametrize("supplied,held,least", [
    ("1.6 TDI", "1.6 TDI CR", 0.6),      # the catalog is more specific
    ("Golf", "Golf 1.6 TDI", 0.5),       # the listing is less specific
    ("VW", "Volkswagen", 0.25),          # an undeclared abbreviation
])
def test_values_that_mean_the_same_thing_score_above_the_cut(supplied, held, least):
    assert _closeness(supplied, held) >= least


@pytest.mark.parametrize("supplied,held", [
    ("Golf", "Passat"),
    # Two letters apart, opposite meanings. Ungated character similarity reads
    # this as 0.33 and matches a diesel listing onto a petrol subject.
    ("petrol", "diesel"),
    ("makita", "volkswagen"),
])
def test_values_that_mean_different_things_score_at_the_bottom(supplied, held):
    from kriko.lookup.score import SIMILAR_ENOUGH

    assert _closeness(supplied, held) < SIMILAR_ENOUGH
