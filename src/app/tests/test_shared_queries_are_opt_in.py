"""Sharing which products were looked up: off by default, and only a product.

The reader ticks one box, and what crosses the wire is the model they looked up
and whether the catalog had it. These tests read the bytes that would be sent,
so a future field has to be argued for here.
"""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient

from app import queryshare
from app.web import state
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
    - {term_id: mech, role: domain}
"""

SUBJECTS = """
    - kind: product
      label: Acme Roadster
      identity: {brand: acme, model: roadster}
      aliases: ["Acme Roadster"]
"""

CLAIMS = """
    - subject: {kind: product, identity: {brand: acme, model: roadster}}
      kind: known_issue
      domain: mech
      severity: high
      text: {en: {title: Timing chain stretches early, body: b, advice: a}}
      evidence:
        - {url: "https://e.invalid/x", quote: Chains go at 80k.}
"""


@pytest.fixture(autouse=True)
def nothing_leaves_the_machine(monkeypatch):
    monkeypatch.setenv("KRIKO_NO_QUERY_SHARE", "1")
    monkeypatch.setenv("KRIKO_QUERIES_URL", "https://gateway.invalid")
    queryshare.clear()
    queryshare._last_sent = 0.0
    yield
    queryshare.clear()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    class Response:
        def close(self):
            return None

    def fake_open(url, body, timeout):
        calls.append({"url": url, "body": body, "timeout": timeout})
        return Response()

    monkeypatch.setattr(queryshare, "_open", fake_open)
    return calls


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent(TERMS), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent(SUBJECTS), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(CLAIMS), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")

    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    return TestClient(create_app(Settings(
        store_path=store_path,
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    )))


def _turn_on(client):
    assert client.put("/api/prefs", json={"share_queries": "1"}).status_code == 200


def _lookup(client, **identity):
    r = client.post("/api/lookup", json={"identity": identity})
    assert r.status_code == 200, r.text
    return r.json()


def test_off_by_default_and_nothing_is_queued_or_sent(client, sent):
    body = _lookup(client, brand="Acme", model="Roadster")
    assert body["subjects"]
    assert queryshare.pending() == []
    assert queryshare.flush() is False
    assert sent == []


def test_turned_on_a_hit_carries_only_the_query_outcome_and_report(client, sent):
    _turn_on(client)
    _lookup(client, brand="Acme", model="Roadster", url="https://shop.invalid/secret-listing")
    assert queryshare.flush() is True
    assert len(sent) == 1
    assert sent[0]["url"] == "https://gateway.invalid/v1/queries"
    payload = json.loads(sent[0]["body"])
    assert set(payload) == {"queries"}
    assert len(payload["queries"]) == 1
    item = payload["queries"][0]
    assert item["q"] == "acme roadster"
    assert item["outcome"] == "hit"
    assert set(item) <= {"q", "outcome", "report", "category"}
    assert "secret-listing" not in sent[0]["body"].decode()
    assert b"shop.invalid" not in sent[0]["body"]


def test_a_miss_is_an_identity_the_catalog_does_not_hold(client, sent):
    _turn_on(client)
    body = _lookup(client, brand="Zephyr", model="Roadster")
    assert body["subjects"] == []
    queryshare.flush()
    item = json.loads(sent[0]["body"])["queries"][0]
    assert item == {"q": "zephyr roadster", "outcome": "miss"}


def test_the_request_carries_no_authorization_and_no_identifying_agent(monkeypatch):
    queryshare._last_sent = 0.0
    queryshare._queue.append({"q": "acme roadster", "outcome": "hit"})
    seen = {}

    class Captured:
        def __init__(self, url, data=None, headers=None, method=None):
            seen.update({"url": url, "data": data, "headers": headers, "method": method})
            raise OSError("offline")

    monkeypatch.setattr(queryshare.urllib.request, "Request", Captured)
    assert queryshare.flush() is False
    assert seen["method"] == "POST"
    assert seen["headers"]["User-Agent"] == "kriko"
    assert not any(key.lower() in {"authorization", "cookie"} for key in seen["headers"])


def test_turning_it_off_clears_what_was_waiting(client, sent):
    _turn_on(client)
    _lookup(client, brand="Acme", model="Roadster")
    assert queryshare.pending()
    assert client.put("/api/prefs", json={"share_queries": "0"}).status_code == 200
    assert queryshare.pending() == []
    assert queryshare.flush() is False
    assert sent == []


def test_an_identity_without_brand_and_model_is_dropped(client, sent):
    _turn_on(client)
    _lookup(client, model="Roadster")
    _lookup(client, brand="Acme")
    assert queryshare.pending() == []
    assert queryshare.flush() is False
    assert sent == []


def test_a_failed_send_is_swallowed_and_does_not_raise(monkeypatch):
    def boom(url, body, timeout):
        raise OSError("offline")

    monkeypatch.setattr(queryshare, "_open", boom)
    queryshare._last_sent = 0.0
    queryshare._queue.append({"q": "acme roadster", "outcome": "miss"})
    assert queryshare.flush() is False


def test_the_queue_holds_no_timestamps_and_sends_at_most_twenty(sent, monkeypatch):
    monkeypatch.setattr(queryshare, "_start_flush", lambda: None)
    queryshare._last_sent = 0.0
    for n in range(25):
        queryshare._queue.append({"q": f"acme roadster{n}", "outcome": "miss"})
    assert len(queryshare.pending()) == 25
    assert queryshare.flush() is True
    items = json.loads(sent[0]["body"])["queries"]
    assert len(items) == 20
    assert all(set(item) == {"q", "outcome"} for item in items)
    assert len(queryshare.pending()) == 0


def test_the_setting_is_a_boolean_the_api_validates(client):
    assert client.put("/api/prefs", json={"share_queries": "yes"}).status_code == 422
    assert client.put("/api/prefs", json={"share_queries": "1"}).status_code == 200
    conn = state.connect(client.app.state.settings.app_state_path)
    try:
        assert state.all_settings(conn)["share_queries"] == "1"
    finally:
        conn.close()


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
    },
    "context": {},
}


def test_a_page_read_is_shared_as_its_identity_never_its_title(client, sent, tmp_path):
    root = tmp_path / "q"
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent(TERMS), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent(SUBJECTS), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(CLAIMS), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    (root / "adapters" / "any_site.json").write_text(json.dumps(ANY_SITE), encoding="utf-8")
    store_path = tmp_path / "any.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "q.kpack"))
    conn.close()
    reading = TestClient(create_app(Settings(
        store_path=store_path,
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    )))
    _turn_on(reading)
    r = reading.post("/api/analyze", json={
        "url": "https://shop.invalid/private-listing",
        "origin": "extension",
        "title": "Acme Roadster 2.0 sifir | Shop",
        "fields": {"ld:@type": "car", "ld:manufacturer": "Acme", "ld:model": "Roadster"},
        "product_name": "Acme Roadster 2.0",
    })
    assert r.status_code == 200, r.text
    assert r.json()["subjects"]
    queryshare.flush()
    item = json.loads(sent[0]["body"])["queries"][0]
    assert item["q"] == "acme roadster"
    assert item["outcome"] == "hit"
    assert item["category"] == "product"
    assert "private-listing" not in sent[0]["body"].decode()
    assert b"Shop" not in sent[0]["body"]
