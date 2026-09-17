"""Typing a product's name, when standing on its page is not an option.

"The extension has no way to search for a particular product. I have to be
standing on the right page and hope recognition fires."

The fixture is two variants of one thing, because that is the case the reader
actually described: a search that cannot tell them apart has not helped.
"""

import textwrap

import pytest

from kriko.lookup import find
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: component, role: subject_kind}
- {term_id: part_of, role: predicate}
- {term_id: part, role: attribute, datatype: text}
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
component = ["part"]
"""

SUBJECTS = """
- kind: product
  label: Widget VII 1.5 SX
  identity: {brand: acme, model: widget7, engine: "1.5 sx"}
  aliases: ["Widget Mk7 petrol", "W7 SX"]
- kind: component
  label: Shared drive belt
  identity: {part: drive_belt}
- kind: product
  label: Widget VII 1.6 DX
  identity: {brand: acme, model: widget7, engine: "1.6 dx"}
  relations:
    - {predicate: part_of, object: {kind: component, identity: {part: drive_belt}}}
- kind: product
  label: Gadget B8 2.0 DX
  identity: {brand: acme, model: gadget8, engine: "2.0 dx"}
"""

CLAIMS = """
- subject: {kind: component, identity: {part: drive_belt}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Belt tensioner fails, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/2", quote: The tensioner wears early.}
- subject: {kind: product, identity: {brand: acme, model: widget7, engine: "1.5 sx"}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Belt due as a kit, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/1", quote: Replace the belt with the pump.}
"""


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "p"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    conn = connect(tmp_path / "s.sqlite")
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    yield conn
    conn.close()


def _labels(rows):
    return [one["label"] for one in rows]


# ── the three places a name lives ───────────────────────────────────────

def test_a_label_is_searched(store):
    assert _labels(find.search(store, "gadget")) == ["Gadget B8 2.0 DX"]


def test_an_alias_is_searched(store):
    """`subject_aliases` holds the phrases people actually type — which is
    the entire reason that table exists."""
    assert _labels(find.search(store, "Mk7")) == ["Widget VII 1.5 SX"]


def test_an_identity_value_is_searched(store):
    """Somebody typing an engine is searching for an engine, not a label."""
    found = find.search(store, "1.6")
    assert _labels(found) == ["Widget VII 1.6 DX"]


def test_an_alias_outranks_a_label_when_both_match(store):
    """When the two disagree about which subject a typed word means, the table
    built for typing is the one to believe."""
    found = find.search(store, "widget")
    assert found[0]["label"] == "Widget VII 1.5 SX"


# ── and what makes the result usable ────────────────────────────────────

def test_every_result_carries_its_identity(store):
    """Two rows reading the same label are not a choice. Telling variants apart
    is the whole ask."""
    found = find.search(store, "widget7")
    assert len(found) == 2
    engines = sorted(one["identity"]["engine"] for one in found)
    assert engines == ["1.5 sx", "1.6 dx"]


def test_a_result_counts_the_claims_it_would_actually_serve(store):
    """Not the claims on its own row — the ones the panel would show.

    A catalog may hang its claims on shared component subjects and reach them
    through `part_of`, so a product row can carry none of its own and still
    answer with several. Measured against `packs/cars` before this was fixed,
    every Golf variant reported `0 claim(s)` while the panel for the same car
    showed a full page. A search result promising nothing about a product the
    reader is about to be shown eight risks for is worse than no number.
    """
    found = find.search(store, "widget7")
    known = {one["label"]: one["claims"] for one in found}
    assert known["Widget VII 1.5 SX"] == 1, "its own claim"
    assert known["Widget VII 1.6 DX"] == 1, (
        "none of its own, one through the component it shares")


def test_a_subject_the_packs_know_something_about_comes_first(store):
    found = find.search(store, "widget vii")
    assert found[0]["claims"] >= found[-1]["claims"]


def test_a_result_says_why_it_matched(store):
    found = find.search(store, "1.5")
    assert any("engine=1.5 sx" in one for one in found[0]["why"])


# ── narrowing ───────────────────────────────────────────────────────────

def test_two_words_narrow_rather_than_widen(store):
    """An `any` match turns "widget dx" into every widget and every DX."""
    assert _labels(find.search(store, "widget dx")) == ["Widget VII 1.6 DX"]


def test_words_may_land_in_different_fields(store):
    """"widget7" on an identity value and "1.5" on another — the common case."""
    assert _labels(find.search(store, "widget7 1.5")) == ["Widget VII 1.5 SX"]


def test_a_word_nothing_holds_returns_nothing_rather_than_everything(store):
    assert find.search(store, "widget zzz") == []


def test_an_empty_query_is_not_a_request_for_the_catalogue(store):
    assert find.search(store, "") == []
    assert find.search(store, "   ") == []


# ── boundaries ──────────────────────────────────────────────────────────

def test_a_disabled_pack_is_not_searched(store):
    packstore.set_enabled(store, "motors", False)
    assert find.search(store, "widget") == []


def test_the_result_order_is_total_so_a_second_press_agrees(store):
    assert find.search(store, "acme") == find.search(store, "acme")


def test_the_limit_is_respected(store):
    assert len(find.search(store, "acme", limit=1)) == 1
