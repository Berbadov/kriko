"""A product's own page lists what applies to it, not only its own rows.

A car variant holds no claims itself; its engine and gearbox do, and a check
on the variant reaches them through its parts. The product view said "No
claim is stored for this subject", which is the screen the panel's "pick the
one on the listing" buttons open. It now asks the engine's lookup.
"""

import textwrap

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: component, role: subject_kind}
- {term_id: part_of, role: predicate}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model, role: attribute, datatype: text, match: {required: true}}
- {term_id: part, role: attribute, datatype: text}
- {term_id: mech, role: domain}
"""
SUBJECTS = """
- kind: component
  label: Pump
  identity: {part: pump}
- kind: product
  label: Widget 100
  identity: {brand: acme, model: w100}
  relations:
    - {predicate: part_of, object: {kind: component, identity: {part: pump}}}
"""
CLAIMS = """
- subject: {kind: component, identity: {part: pump}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Pump seal leaks, body: b, advice: a}}
  evidence:
    - {url: "https://forum.example.org/t/1", quote: The seal went at two years.}
"""


def _client(tmp_path):
    root = tmp_path / "p"
    for d in ("vocabulary", "data"):
        (root / d).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent("""
        [pack]
        id = "widgets"
        name = "Widgets"
        version = "0.1.0"
        [identity]
        product = ["brand", "model"]
        component = ["part"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(CLAIMS, encoding="utf-8")
    store = connect(tmp_path / "knowledge.sqlite")
    packstore.install(store, build.build(root, tmp_path / "w.kpack"))
    store.commit()
    store.close()
    return TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl")))


def test_a_product_lists_the_claims_of_its_parts_and_names_the_part(tmp_path):
    client = _client(tmp_path)
    [product] = [s for s in client.get("/api/subjects", params={"pack_id": "widgets"}).json()
                 if s["label"] == "Widget 100"]
    detail = client.get(f"/api/subjects/{product['subject_id']}").json()
    assert [(c["title"], c["via"]) for c in detail["claims"]] == [("Pump seal leaks", "Pump")]


def test_a_part_lists_its_own_claims(tmp_path):
    client = _client(tmp_path)
    [part] = [s for s in client.get("/api/subjects", params={"pack_id": "widgets"}).json()
              if s["label"] == "Pump"]
    detail = client.get(f"/api/subjects/{part['subject_id']}").json()
    assert [c["title"] for c in detail["claims"]] == ["Pump seal leaks"]
