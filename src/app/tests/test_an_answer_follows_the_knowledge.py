"""B152.4: "a card added by the agent, we instantly see the new card".

An open answer — the app's Result screen, the extension's panel — watches one
clock and, when it moves, asks for its saved question to be answered again.
These pin the two halves at the API: the clock moves on a write from another
connection (the MCP server is another process), and a re-answer carries the
new card without becoming a second history row, operation or log line.
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

URL = "https://market.invalid/listing/42"
PAGE = {"brand": "Acme", "series": "Roadster", "km": "95.000"}

CLAIM = """
- subject: {kind: product, identity: {brand: acme, model: roadster}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Timing chain stretches early, body: b, advice: a}}
  evidence:
    - {url: "https://e.invalid/x", quote: Chains go at 80k.}
"""


def _pack(root, version, claims):
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "pack.toml").write_text(textwrap.dedent(f"""
        [pack]
        id = "machines"
        name = "machines"
        version = "{version}"
        license = "CC0-1.0"
        [identity]
        product = ["brand", "model"]
    """), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent("""
        - {term_id: product, role: subject_kind}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: usage_km, role: context_key, datatype: number, unit: km}
        - {term_id: mech, role: domain}
    """), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent("""
        - kind: product
          label: Acme Roadster
          identity: {brand: acme, model: roadster}
    """), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(claims) or "[]\n",
                                               encoding="utf-8")
    (root / "research" / "principle.md").write_text("The bar.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    (root / "adapters" / "market.json").write_text(json.dumps({
        "id": "market", "site": "market.invalid", "subject_kind": "product",
        "match": ["https://market.invalid/listing/*"],
        "identity": {"brand": {"labels": ["brand"], "vocabulary": "brand"},
                     "model": {"labels": ["series"], "vocabulary": "model"}},
        "context": {"usage_km": {"labels": ["km"], "parse": "int_range",
                                 "min": 0, "max": 2000000}},
    }), encoding="utf-8")
    return root


def _install(tmp_path, version, claims):
    conn = connect(tmp_path / "store.sqlite")
    try:
        root = _pack(tmp_path / f"src-{version}", version, claims)
        packstore.install(conn, build.build(root, tmp_path / f"machines-{version}.kpack"))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path):
    _install(tmp_path, "0.1.0", "")
    app = create_app(Settings(
        store_path=tmp_path / "store.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    ))
    with TestClient(app) as test_client:
        test_client.tmp = tmp_path
        yield test_client


def _clock(client):
    return client.get("/api/knowledge/clock").json()["clock"]


def test_the_clock_stands_still_while_nothing_is_written(client):
    first = _clock(client)
    assert _clock(client) == first
    client.post("/api/analyze", json={"url": URL, "origin": "extension", "fields": PAGE})
    # Reading the knowledge, and writing history, are not knowledge changes.
    assert _clock(client) == first


def test_a_write_from_another_connection_moves_the_clock(client):
    first = _clock(client)
    _install(client.tmp, "0.1.1", CLAIM)
    assert _clock(client) != first


def test_the_extensions_live_poll_carries_the_clock(client):
    assert client.get("/api/operations?limit=6").json()["knowledge"] == _clock(client)


def test_a_saved_answer_is_answered_again_with_the_new_card(client):
    before = client.post("/api/analyze", json={
        "url": URL, "origin": "extension", "fields": PAGE}).json()
    assert before["claims"] == []
    lookup_id = before["lookup_id"]
    history = client.get("/api/history").json()["items"]
    operations = client.get("/api/operations").json()["items"]
    log = (client.tmp / "analyses.jsonl").read_text(encoding="utf-8")

    _install(client.tmp, "0.1.1", CLAIM)
    refreshed = client.post(f"/api/lookup/{lookup_id}/refresh").json()

    assert refreshed["refreshed"] is True
    assert refreshed["lookup_id"] == lookup_id
    assert [c["title"] for c in refreshed["response"]["claims"]] == [
        "Timing chain stretches early"]
    assert refreshed["response"]["url"] == URL
    # Written over the saved answer, so reopening it shows the card too...
    reopened = client.get(f"/api/lookup/{lookup_id}").json()
    assert len(reopened["response"]["claims"]) == 1
    # ...and nothing else recorded a second analysis.
    assert len(client.get("/api/history").json()["items"]) == len(history) == 1
    assert len(client.get("/api/operations").json()["items"]) == len(operations)
    assert (client.tmp / "analyses.jsonl").read_text(encoding="utf-8") == log


def test_an_asked_lookup_is_answered_again_too(client):
    asked = client.post("/api/lookup", json={
        "kind": "product", "identity": {"brand": "acme", "model": "roadster"},
        "context": {}}).json()
    assert asked["claims"] == []
    _install(client.tmp, "0.1.1", CLAIM)
    refreshed = client.post(f"/api/lookup/{asked['lookup_id']}/refresh").json()
    assert len(refreshed["response"]["claims"]) == 1


def test_refreshing_what_is_not_there_is_a_404(client):
    assert client.post("/api/lookup/deadbeef/refresh").status_code == 404
