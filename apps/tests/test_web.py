"""The local dashboard.

The app is built by a factory taking `Settings`, which is what makes these tests
possible at all: each builds an app pointed at its own temporary store. The old
hub computed its paths as import-time module constants, so its endpoints could
not be tested without monkeypatching the module and two tests could not run
against two stores. That coupling is what blocked backlog B28's router split.
"""

import textwrap

import pytest
from fastapi.testclient import TestClient

from apps.web.app import create_app
from apps.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

PACK = {
    "toml": """
        [pack]
        id = "tools"
        name = "Tools"
        version = "0.2.0"
        license = "CC0-1.0"
        [identity]
        product = ["brand", "model"]
        platform = ["brand", "platform"]
    """,
    "terms": """
        - {term_id: product, role: subject_kind}
        - {term_id: platform, role: subject_kind}
        - {term_id: part_of, role: predicate}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: platform, role: attribute, datatype: text}
        - {term_id: usage_hours, role: context_key, datatype: number, unit: hours}
        - {term_id: mech, role: domain}
    """,
    "subjects": """
        - kind: platform
          label: LXT 18V
          identity: {brand: makita, platform: LXT}
        - kind: product
          label: Makita DHP484
          identity: {brand: makita, model: DHP484}
          relations:
            - {predicate: part_of, object: {kind: platform, identity: {brand: makita, platform: LXT}}}
        - kind: product
          label: Orphan Tool
          identity: {brand: acme, model: orphan}
    """,
    "claims": """
        - subject: {kind: platform, identity: {brand: makita, platform: LXT}}
          kind: known_issue
          domain: mech
          severity: high
          text: {en: {title: Cell imbalance trips protection, body: b, advice: a}}
          conditions:
            - {key: usage_hours, op: gte, value: 400, on_missing: open, weight: 0.7}
          evidence:
            - {url: "https://e.invalid/x", quote: Packs past 400 hours drift.}
            - {url: "https://f.invalid/y", quote: Mine is fine at 900., stance: refutes}
    """,
}


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(PACK["toml"]), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(PACK["terms"]), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(PACK["subjects"]), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(
        textwrap.dedent(PACK["claims"]), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")

    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    return TestClient(create_app(Settings(store_path=store_path)))


# ── the page itself ──────────────────────────────────────────────────────

def test_the_page_and_its_assets_are_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_health_reports_which_store_it_is_looking_at(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["store"].endswith("store.sqlite")


# ── packs ────────────────────────────────────────────────────────────────

def test_packs_lists_what_is_installed_with_its_contents(client):
    (pack,) = client.get("/api/packs").json()
    assert pack["pack_id"] == "tools"
    assert pack["subjects"] == 3
    assert pack["claims"] == 1
    assert pack["license"] == "CC0-1.0"
    assert pack["enabled"] is True


def test_disabling_a_pack_hides_it_from_reads_without_deleting_it(client):
    client.post("/api/packs/tools/enabled?enabled=false")
    assert client.get("/api/subjects").json() == []
    # ...but the rows are still there, so re-enabling is free.
    assert client.get("/api/packs").json()[0]["subjects"] == 3
    client.post("/api/packs/tools/enabled?enabled=true")
    assert client.get("/api/subjects").json()


def test_uninstalling_an_absent_pack_is_a_404(client):
    assert client.delete("/api/packs/nope").status_code == 404


def test_the_vocabulary_endpoint_reports_the_packs_own_words(client):
    vocab = client.get("/api/packs/tools/vocabulary").json()
    assert {t["term_id"] for t in vocab["context_key"]} == {"usage_hours"}
    assert vocab["context_key"][0]["unit"] == "hours"


# ── the form builds itself from pack data ────────────────────────────────

def test_identity_keys_come_from_the_pack_not_from_the_page(client):
    """Nothing in the UI knows what a drill or a car is.

    It asks which attributes identify a subject in the chosen pack and builds
    inputs for those, so a new category changes the form without changing a line
    of the page.
    """
    keys = {k["key"] for k in client.get("/api/identity-keys/tools").json()}
    assert keys == {"brand", "model", "platform"}


def test_kinds_are_reported_per_pack(client):
    kinds = client.get("/api/kinds").json()
    assert {k["kind"] for k in kinds} == {"product", "platform"}


# ── asking ───────────────────────────────────────────────────────────────

def test_a_lookup_returns_claims_with_their_reasons_and_sources(client):
    body = client.post("/api/lookup", json={
        "kind": "product", "identity": {"brand": "makita", "model": "DHP484"},
        "context": {"usage_hours": 900}}).json()

    assert body["method"] == "exact"
    assert body["coverage"] == "RISKS_FOUND"
    (claim,) = body["claims"]
    assert claim["title"] == "Cell imbalance trips protection"
    assert claim["subject"] == "LXT 18V"       # reached through part_of
    assert claim["why"], "every claim must explain its own rank"
    assert {s["stance"] for s in claim["sources"]} == {"supports", "refutes"}
    assert claim["disputed"] is True


def test_an_unknown_thing_answers_rather_than_erroring(client):
    body = client.post("/api/lookup", json={
        "kind": "product", "identity": {"brand": "nobody", "model": "nothing"}}).json()
    assert body["method"] == "no_match"
    assert body["claims"] == []


def test_an_unstated_context_value_still_returns_the_claim(client):
    """Fail-open, visible through the API."""
    body = client.post("/api/lookup", json={
        "kind": "product", "identity": {"brand": "makita", "model": "DHP484"}}).json()
    (claim,) = body["claims"]
    assert any("usage_hours not stated" in reason for reason in claim["why"])


# ── browsing ─────────────────────────────────────────────────────────────

def test_subject_detail_shows_attributes_relations_and_claims(client):
    subjects = client.get("/api/subjects?q=DHP484").json()
    detail = client.get(f"/api/subjects/{subjects[0]['subject_id']}").json()
    assert detail["label"] == "Makita DHP484"
    assert {a["key"] for a in detail["attributes"]} == {"brand", "model"}
    assert detail["relations"][0]["object_label"] == "LXT 18V"


def test_an_unknown_subject_is_a_404(client):
    assert client.get("/api/subjects/nope").status_code == 404


def test_the_brief_endpoint_carries_the_packs_principle(client):
    subjects = client.get("/api/subjects?q=DHP484").json()
    brief = client.get(f"/api/subjects/{subjects[0]['subject_id']}/brief").json()
    assert "Only the expensive." in brief["brief"]
    assert brief["queries"] == ["Makita DHP484 faults"]


# ── coverage ─────────────────────────────────────────────────────────────

def test_a_gap_is_a_subject_nothing_reaches_even_through_relations(client):
    """Counting direct claims alone would call every car unresearched.

    A car's claims live on its engine and gearbox, not on the car. The Makita
    has no claims of its own but reaches one through `part_of`; only the
    genuinely orphaned tool is a gap.
    """
    gaps = client.get("/api/packs/tools/gaps").json()
    assert [g["label"] for g in gaps] == ["Orphan Tool"]
