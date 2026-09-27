"""B149: a product on a site no adapter covers is still read.

The reader's words: *"new products aren't recognised, in new sites products
can't be grabbed"* — on other car sites and on big retail. The extension now
sends every page's schema.org product data (`ld:*` labels) and the product's
own name, so the server has two ways to read a page no site adapter claims:
a pack's **any-site adapter**, then the product's **name** against every
subject's label and aliases. What neither knows comes back as
`unknown_product` with its name, which the panel offers to research.
"""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TOML = """
    [pack]
    id = "machines"
    name = "Machines"
    version = "0.1.0"
    license = "CC0-1.0"
    [identity]
    product = ["brand", "model"]
"""

TERMS = """
    - {term_id: product, role: subject_kind}
    - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
    - {term_id: model, role: attribute, datatype: text, match: {required: true}}
    - {term_id: fuel, role: attribute, datatype: text}
    - {term_id: petrol, role: enum_value, parent: fuel, aliases: [gasoline]}
    - {term_id: usage_km, role: context_key, datatype: number, unit: km}
    - {term_id: mech, role: domain}
"""

SUBJECTS = """
    - kind: product
      label: Acme Roadster
      identity: {brand: acme, model: roadster, fuel: petrol}
      aliases: ["Acme Roadster"]
    - kind: product
      label: Makita DHP484 combi drill
      identity: {brand: makita, model: DHP484}
      aliases: [DHP484Z, "DHP 484"]
"""

CLAIMS = """
    - subject: {kind: product, identity: {brand: acme, model: roadster, fuel: petrol}}
      kind: known_issue
      domain: mech
      severity: high
      text: {en: {title: Timing chain stretches early, body: b, advice: a}}
      evidence:
        - {url: "https://e.invalid/x", quote: Chains go at 80k.}
    - subject: {kind: product, identity: {brand: makita, model: DHP484}}
      kind: known_issue
      domain: mech
      severity: low
      text: {en: {title: Chuck loosens under hammer, body: b, advice: a}}
      evidence:
        - {url: "https://e.invalid/y", quote: Chuck slips.}
"""

#: Shaped like `packs/cars/adapters/any_site.json`: vehicle pages only, a
#: brand and model the pack already holds, both required.
ANY_SITE = {
    "id": "machines.any_site",
    "site": "",
    "any_site": True,
    "subject_kind": "product",
    "page_types": ["car", "vehicle"],
    "requires": ["brand", "model"],
    "match": [],
    "identity": {
        "brand": {"labels": ["ld:manufacturer", "ld:brand"], "vocabulary": "brand",
                  "known": True, "from": "title"},
        "model": {"labels": ["ld:model", "ld:name"], "vocabulary": "model",
                  "known": True, "from": "title"},
        "fuel": {"labels": ["ld:vehicleEngine.fuelType", "ld:fuelType"]},
    },
    "context": {
        "usage_km": {"labels": ["ld:mileageFromOdometer"], "parse": "int_range",
                     "min": 0, "max": 2000000},
    },
}


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent(TERMS), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent(SUBJECTS), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(CLAIMS), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    (root / "adapters" / "any_site.json").write_text(json.dumps(ANY_SITE), encoding="utf-8")

    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    return TestClient(create_app(Settings(
        store_path=store_path,
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    )))


def _analyze(client, **body):
    body.setdefault("url", "https://shop.invalid/p/1")
    body.setdefault("origin", "extension")
    r = client.post("/api/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_car_on_a_site_nobody_wrote_an_adapter_for_is_read_from_its_schema_data(client):
    body = _analyze(client, fields={
        "ld:@type": "car", "ld:manufacturer": "Acme", "ld:model": "Roadster",
        "ld:vehicleEngine.fuelType": "Gasoline", "ld:mileageFromOdometer": "95000",
    }, product_name="Acme Roadster 2.0")
    assert body["read_by"] == "any_site"
    assert body["identity"]["brand"] == "acme"
    assert body["identity"]["model"] == "roadster"
    assert body["context"]["usage_km"] == 95000
    assert [c["title"] for c in body["claims"]] == ["Timing chain stretches early"]


def test_the_any_site_adapter_is_never_listed_as_a_site(client):
    assert client.get("/api/adapters").json() == []


def test_a_phone_page_is_never_read_as_a_car(client):
    """A shop's Product with a brand the pack does not hold, and a page type
    that is not a vehicle: neither gate lets it through."""
    body = _analyze(client, fields={
        "ld:@type": "product", "ld:brand": "Apple", "ld:model": "A2846",
    }, product_name="Apple iPhone 15 128GB")
    assert body["readable"] is False
    assert body["reason"] == "unknown_product"
    assert body["product"]["name"] == "Apple iPhone 15 128GB"


def test_an_unknown_brand_on_a_car_page_is_unknown_not_a_wrong_car(client):
    body = _analyze(client, fields={
        "ld:@type": "car", "ld:manufacturer": "Zephyr", "ld:model": "Roadster",
    }, product_name="Zephyr Roadster")
    assert body["reason"] == "unknown_product"


def test_a_retail_page_is_recognised_by_its_product_name(client):
    """No schema data a pack reads — just the shop's product name, which
    carries the pack's own alias."""
    body = _analyze(client, fields={"ld:@type": "product", "ld:brand": "Makita"},
                    product_name="Makita DHP484Z 18V Akulu Darbeli Matkap")
    assert body["read_by"] == "name"
    assert body["identity"] == {"brand": "makita", "model": "DHP484"}
    assert [c["title"] for c in body["claims"]] == ["Chuck loosens under hammer"]


def test_a_single_plain_word_names_nothing(client):
    """"Drill" is on every drill page; only a whole alias or a model code may
    name one product."""
    body = _analyze(client, product_name="Roadster bike helmet")
    assert body["reason"] == "unknown_product"


def test_a_page_that_names_no_product_keeps_the_old_answer(client):
    body = _analyze(client, fields={})
    assert body["reason"] == "no_adapter"
