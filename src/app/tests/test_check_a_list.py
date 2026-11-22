"""Check a list: one request matches a spreadsheet's worth of names to the catalogs.

A buyer's sheet names products in their own words. The route reads each name the
way the engine does elsewhere (the catalog's name inside the row, or every word
of the row on one product), never guesses between two products, and reports
each match's claims in the engine's severity words. These tests run against a
real installed catalog; no product is known to the route itself.
"""

import textwrap

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model, role: attribute, datatype: text, match: {required: true}}
- {term_id: mech, role: domain}
"""
SUBJECTS = """
- kind: product
  label: Acme Roadster
  identity: {brand: acme, model: roadster}
  aliases: ["Roadster R1"]
- kind: product
  label: Acme Roadster Plus
  identity: {brand: acme, model: roadster plus}
- kind: product
  label: Zeta Coupe
  identity: {brand: zeta, model: coupe}
- kind: product
  label: Beta Wagon 200
  identity: {brand: beta, model: wagon 200}
- kind: product
  label: Beta Wagon 300
  identity: {brand: beta, model: wagon 300}
"""


def _claim(brand, model, severity, title):
    return textwrap.dedent(f"""
        - subject: {{kind: product, identity: {{brand: {brand}, model: {model}}}}}
          kind: known_issue
          domain: mech
          severity: {severity}
          text: {{en: {{title: "{title}", body: b, advice: a}}}}
          evidence:
            - {{url: "https://forum.example.org/t/{title.replace(' ', '')}", quote: The {title} went wrong.}}
    """)


CLAIMS = (
    _claim("acme", "roadster", "high", "Gearbox whine")
    + _claim("acme", "roadster", "high", "Seat rattle")
    + _claim("acme", "roadster", "medium", "Paint chips")
    + _claim("acme", "roadster", "low", "Squeaky pedal")
    + _claim("zeta", "coupe", "medium", "Slow charging")
)


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "p"
    for d in ("vocabulary", "data"):
        (root / d).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent("""
        [pack]
        id = "machines"
        name = "Machines"
        version = "0.1.0"
        [identity]
        product = ["brand", "model"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    store = connect(tmp_path / "knowledge.sqlite")
    packstore.install(store, build.build(root, tmp_path / "m.kpack"))
    store.commit()
    store.close()
    with TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl"))) as test_client:
        yield test_client


def _check(client, *names):
    reply = client.post("/api/check-list", json={"names": list(names)})
    assert reply.status_code == 200, reply.text
    return reply.json()["items"]


def test_a_name_that_is_exactly_a_product_matches_it_with_its_severity_counts(client):
    [item] = _check(client, "Acme Roadster")
    assert item["index"] == 0 and item["query"] == "Acme Roadster"
    assert item["match"]["label"] == "Acme Roadster"
    assert item["match"]["pack_id"] == "machines"
    assert item["match"]["confidence"] == "exact"
    assert item["claims"] == {"total": 4, "serious": 2, "known": 1, "minor": 1}
    assert item["leading"]["severity"] == "high"
    assert item["leading"]["title"] in ("Gearbox whine", "Seat rattle")
    assert item["others"] == []


def test_a_row_with_more_words_than_the_catalog_name_still_matches_the_longest_name(client):
    [item] = _check(client, "Acme Roadster Plus 2.0 turbo, silver, 2022")
    assert item["match"]["label"] == "Acme Roadster Plus"
    assert item["match"]["confidence"] == "name"


def test_an_alias_is_a_name(client):
    [item] = _check(client, "roadster r1")
    assert item["match"]["label"] == "Acme Roadster"


def test_words_that_sit_on_one_product_match_it(client):
    [item] = _check(client, "coupe")
    assert item["match"]["label"] == "Zeta Coupe"
    assert item["match"]["confidence"] == "words"
    assert item["claims"]["known"] == 1 and item["leading"] == {"title": "Slow charging", "severity": "medium"}


def test_a_product_with_no_reports_is_a_match_with_nothing_to_say(client):
    [item] = _check(client, "Beta Wagon 200")
    assert item["match"]["label"] == "Beta Wagon 200"
    assert item["claims"] == {"total": 0, "serious": 0, "known": 0, "minor": 0}
    assert item["leading"] is None


def test_a_name_no_catalog_holds_is_not_a_match_and_has_no_candidates(client):
    items = _check(client, "Completely unrelated garden gnome", "zzzz")
    for item in items:
        assert item["match"] is None and item["others"] == []
        assert item["claims"]["total"] == 0


def test_two_products_that_fit_equally_are_candidates_and_never_a_guess(client):
    [item] = _check(client, "Beta Wagon")
    assert item["match"] is None
    assert sorted(o["label"] for o in item["others"]) == ["Beta Wagon 200", "Beta Wagon 300"]
    # A candidate says what it holds, so choosing one needs no second request.
    assert all("claims" in o and "leading" in o for o in item["others"])


def test_a_name_is_not_a_product_because_it_is_a_prefix_of_two(client):
    [item] = _check(client, "Acme")
    assert item["match"] is None
    assert {o["label"] for o in item["others"]} == {"Acme Roadster", "Acme Roadster Plus"}


def test_every_row_is_answered_in_order_with_its_index(client):
    items = _check(client, "Zeta Coupe", "nothing here", "Acme Roadster")
    assert [i["index"] for i in items] == [0, 1, 2]
    assert [bool(i["match"]) for i in items] == [True, False, True]


def test_three_hundred_names_are_accepted_and_three_hundred_and_one_are_not(client):
    assert len(_check(client, *["Zeta Coupe"] * 300)) == 300
    refused = client.post("/api/check-list", json={"names": ["Zeta Coupe"] * 301})
    assert refused.status_code == 422


@pytest.mark.parametrize("body", [
    {}, {"names": []}, {"names": "Zeta Coupe"}, {"names": [1, 2]}, {"names": ["x" * 201]},
])
def test_bad_input_is_refused_not_answered(client, body):
    assert client.post("/api/check-list", json=body).status_code == 422


def test_a_blank_name_is_an_unmatched_row(client):
    [item] = _check(client, "   ")
    assert item["match"] is None and item["others"] == []


def test_a_percent_sign_is_a_character_not_a_wildcard(client):
    [item] = _check(client, "%")
    assert item["match"] is None and item["others"] == []
