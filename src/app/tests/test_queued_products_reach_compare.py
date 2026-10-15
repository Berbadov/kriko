"""A researched product reaches Compare, and a queued product is resolved the way the catalog names it.

Three things were true at once: a queued listing was matched by its seller's
whole title (every word had to appear in a label), so a product the catalog
already held was treated as unknown; a finished research left no saved check,
so Compare never listed it; and a check that failed to save left the row Done
with nothing to compare. These tests pin the fix at the API boundary and at the
job boundary, against a real installed catalog.
"""

import json
import textwrap
import time

import pytest
from fastapi.testclient import TestClient

from app.web import productchecks, state
from app.web.app import create_app
from app.web.jobs import JobRunner
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

LISTING = "https://market.invalid/listing/9"
TITLE = "ACME ROADSTER 2.0 TURBO 2019 FIRSAT sahibinden temiz"


def _pack(root):
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "pack.toml").write_text(textwrap.dedent("""
        [pack]
        id = "machines"
        name = "machines"
        version = "0.1.0"
        license = "CC0-1.0"
        [identity]
        product = ["brand", "model"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent("""
        - {term_id: product, role: subject_kind}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: mech, role: domain}
    """), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent("""
        - kind: product
          label: Acme Roadster
          identity: {brand: acme, model: roadster}
        - kind: product
          label: Zeta Coupe
          identity: {brand: zeta, model: coupe}
    """), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text("[]\n", encoding="utf-8")
    (root / "research" / "principle.md").write_text("The bar.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    (root / "adapters" / "market.json").write_text(json.dumps({
        "id": "market", "site": "market.invalid", "subject_kind": "product",
        "match": ["https://market.invalid/listing/*"],
        "identity": {"brand": {"labels": ["brand"], "vocabulary": "brand"},
                     "model": {"labels": ["series"], "vocabulary": "model"}},
    }), encoding="utf-8")
    return root


def _settings(tmp_path) -> Settings:
    conn = connect(tmp_path / "store.sqlite")
    try:
        root = _pack(tmp_path / "src")
        packstore.install(conn, build.build(root, tmp_path / "machines.kpack"))
        conn.commit()
    finally:
        conn.close()
    return Settings(
        store_path=tmp_path / "store.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )


def _subject(settings, label):
    conn = connect(settings.store_path)
    try:
        return conn.execute(
            "SELECT subject_id FROM subjects WHERE label = ?", (label,)).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def settings(tmp_path):
    return _settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _run(settings, kind, handler, params):
    """A real job through the runner, waited on: its result and its row."""
    runner = JobRunner(settings, {kind: handler})
    try:
        job_id = runner.submit(kind, params)
        conn = state.connect(settings.app_state_path)
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                row = state.get_job(conn, job_id)
                if row and row["state"] in state.TERMINAL:
                    return job_id, row
                time.sleep(0.05)
        finally:
            conn.close()
    finally:
        runner.shutdown(wait=True)
    raise AssertionError("the job never finished")


def _listed(client, title):
    return client.post("/api/queue", json={"url": LISTING, "name": title}).json()["item"]


def test_a_listing_title_resolves_to_the_catalog_product_it_names(client, settings):
    item = _listed(client, TITLE)

    target = client.get(f"/api/queue/{item['queue_id']}/target")

    assert target.status_code == 200, target.text
    assert target.json()["subject_id"] == _subject(settings, "Acme Roadster")
    assert target.json()["pack_id"] == "machines"


def test_a_title_naming_no_catalog_product_is_not_in_your_catalogs(client):
    item = _listed(client, "Completely different thing from a garage sale")

    target = client.get(f"/api/queue/{item['queue_id']}/target")

    assert target.status_code == 404
    assert target.json()["detail"] == "not in your catalogs"


def test_checking_a_product_saves_one_refreshed_check_for_it(client, settings):
    subject = _subject(settings, "Acme Roadster")

    first = client.post(f"/api/products/{subject}/check", json={}).json()
    second = client.post(f"/api/products/{subject}/check", json={}).json()

    assert first["lookup_id"] and second["lookup_id"] == first["lookup_id"]
    labels = [row["label"] for row in client.get("/api/history").json()["items"]]
    assert labels.count("Acme Roadster") == 1


def test_a_finished_research_is_in_compare_without_a_further_step(settings, client):
    subject = _subject(settings, "Acme Roadster")

    def research(_settings, params, progress):
        return {"subject_id": subject, "pack_id": "machines", "claims": 0}

    _run(settings, "research", research, {"subject_id": subject})

    labels = [row["label"] for row in client.get("/api/history").json()["items"]]
    assert "Acme Roadster" in labels


def test_a_harvest_that_filed_a_product_saves_its_check_and_names_only_installed_ones(client, settings):
    subject = _subject(settings, "Acme Roadster")
    result = {"filed_quick_looks": ["q1"], "filed_subjects": [
        {"subject_id": subject, "pack_id": "machines"},
        {"subject_id": "not-installed", "pack_id": "machines"},
    ]}

    conn = state.connect(settings.app_state_path)
    try:
        saved = productchecks.record_finished(conn, connect(settings.store_path, read_only=True),
                                              "pack_harvest", result)
    finally:
        conn.close()

    assert saved == [subject]
    labels = [row["label"] for row in client.get("/api/history").json()["items"]]
    assert labels.count("Acme Roadster") == 1


def test_a_job_that_names_no_installed_product_saves_no_check(client, settings):
    before = client.get("/api/history").json()["items"]
    conn = state.connect(settings.app_state_path)
    try:
        saved = productchecks.record_finished(conn, connect(settings.store_path, read_only=True),
                                              "research", {"subject_id": "not-installed"})
    finally:
        conn.close()

    assert saved == []
    assert client.get("/api/history").json()["items"] == before


def test_a_draft_that_did_not_install_says_why_the_queued_product_is_not_there(client, settings):
    item = _listed(client, TITLE)

    def author(_settings, params, progress):
        return {"pack_id": "machines", "subject": {"subject_id": "not-installed"},
                "installed": False,
                "install_error": "the draft does not build: version 0.1.0 is taken"}

    job_id, row = _run(settings, "pack_author", author, {"product": TITLE})
    assert row["state"] == "succeeded"

    target = client.get(f"/api/queue/{item['queue_id']}/target", params={"job_id": job_id})

    assert target.status_code == 404
    assert "the draft does not build" in target.json()["detail"]
