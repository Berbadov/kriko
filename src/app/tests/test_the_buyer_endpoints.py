"""The buyer's routes: profile, ledger, fit, pick, watches and the checkout look."""


import pytest
from fastapi.testclient import TestClient

from app import pricewatch
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("KRIKO_NO_PACK_AUTOUPDATE", "1")
    app = create_app(Settings(store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
                              analysis_log_path=tmp_path / "a.jsonl"))
    with TestClient(app) as client:
        client.app_state_path = tmp_path / "app.sqlite"
        yield client


def rows(client):
    return state.connect(client.app_state_path)


def test_a_new_install_has_an_empty_profile_and_says_nothing(client):
    got = client.get("/api/buyer/profile").json()
    assert got["empty"] is True and got["brief"] == ""
    assert "durability" in got["priorities"]


def test_the_profile_roundtrips_and_is_trimmed(client):
    saved = client.put("/api/buyer/profile", json={
        "about": "I work from home", "budget": {"max": "800", "currency": "eur"},
        "must": "quiet, usb-c", "avoid": ["Acme"], "priorities": {"durability": 5}}).json()
    assert saved["empty"] is False
    again = client.get("/api/buyer/profile").json()
    assert again["profile"]["must"] == ["quiet", "usb-c"]
    assert again["profile"]["budget"]["currency"] == "EUR"
    assert "Avoid: Acme" in again["brief"]


def test_a_purchase_is_recorded_answered_and_forgotten(client):
    made = client.post("/api/buyer/purchases", json={"name": "Kettle", "url": "https://s.test/k",
                                                     "price": "29.9", "currency": "eur"}).json()
    assert made["currency"] == "EUR" and made["verdict"] == ""
    assert client.post("/api/buyer/purchases", json={"name": " "}).status_code == 422
    answered = client.post(f"/api/buyer/purchases/{made['purchase_id']}/answer",
                           json={"verdict": "regret", "reason": "lid cracked"}).json()
    assert answered["verdict"] == "regret"
    assert client.post(f"/api/buyer/purchases/{made['purchase_id']}/answer",
                       json={"verdict": "meh"}).status_code == 422
    assert client.post("/api/buyer/purchases/nope/answer", json={"verdict": "glad"}).status_code == 404
    listing = client.get("/api/buyer/purchases").json()
    assert listing["tally"]["regret"] == 1 and listing["record"]["picks"] == 0
    assert client.delete(f"/api/buyer/purchases/{made['purchase_id']}").status_code == 200
    assert client.delete(f"/api/buyer/purchases/{made['purchase_id']}").status_code == 404


def test_fit_is_empty_until_the_reader_has_said_something(client):
    body = {"items": [{"name": "Acme laptop", "price": 500, "currency": "EUR"}]}
    assert client.post("/api/buyer/fit", json=body).json() == {"profile": False, "items": []}
    client.put("/api/buyer/profile", json={"avoid": ["Acme"]})
    got = client.post("/api/buyer/fit", json=body).json()
    assert got["profile"] is True and got["items"][0]["breaks"] == ["avoid"]


def seed(client, label, url, price, claims=()):
    conn = rows(client)
    request = {"url": url, "title": label, "fields": {"ld:price": str(price), "ld:priceCurrency": "EUR"}}
    lookup_id = state.record_lookup(conn, source="extension", label=label, request=request,
                                    response={"claims": list(claims)})
    conn.close()
    return lookup_id


def test_pick_ranks_the_shortlist_and_names_a_winner(client):
    a = seed(client, "Kettle A", "https://a.test/p/1", 60, [{"title": "Element fails", "severity": "high"}])
    b = seed(client, "Kettle B", "https://b.test/p/1", 66)
    got = client.post("/api/buyer/pick", json={"lookup_ids": [a, b]}).json()
    assert got["picked"]["name"] == "Kettle B" and got["picked"]["lookup_id"] == b
    assert client.post("/api/buyer/pick", json={"lookup_ids": []}).status_code == 422


def test_pick_reads_a_draft_and_the_queue(client):
    a = seed(client, "Kettle A", "https://a.test/p/1", 60)
    b = seed(client, "Kettle B", "https://b.test/p/1", 66)
    conn = rows(client)
    draft = state.save_compare_draft(conn, "kettles", [a, b])
    conn.close()
    assert len(client.post("/api/buyer/pick", json={"draft_id": draft["draft_id"]}).json()["ranked"]) == 2
    assert client.post("/api/buyer/pick", json={"draft_id": "nope"}).status_code == 404


def test_advice_needs_the_right_number_of_saved_checks_and_a_known_mode(client):
    a = seed(client, "Kettle A", "https://a.test/p/1", 60)
    assert client.post("/api/buyer/advice", json={"lookup_ids": [a], "mode": "debate"}).status_code == 422
    assert client.post("/api/buyer/advice", json={"lookup_ids": [a], "mode": "poem"}).status_code == 422


def test_watching_a_page_alerts_when_it_falls_and_the_alert_is_read_once(client):
    url = "https://shop.test/p/kettle"
    made = client.post("/api/prices/watches", json={"url": url, "name": "Kettle", "target": 50,
                                                    "price": 70}).json()
    assert made["target"] == 50
    conn = rows(client)
    pricewatch.record(conn, url, "Kettle", {"price": 45, "currency": "EUR"})
    conn.close()
    alerts = client.get("/api/prices/alerts").json()["items"]
    assert [one["price"] for one in alerts] == [45]
    assert client.post("/api/prices/alerts/read", json={"ids": []}).json() == {"read": 1}
    assert client.get("/api/prices/alerts").json()["items"] == []
    listing = client.get("/api/prices/watches").json()
    assert len(listing["items"]) == 1
    assert client.delete(f"/api/prices/watches/{made['watch_id']}").status_code == 200
    assert client.post("/api/prices/watches", json={"url": "nope"}).status_code == 422


def test_a_sweep_with_nothing_due_starts_no_job(client):
    assert client.post("/api/prices/sweep").json() == {"job_id": "", "due": 0}


def test_the_checkout_look_returns_a_verdict(client):
    got = client.post("/api/prices/checkout", json={
        "url": "https://shop.example/checkout", "text": "we only take bitcoin",
        "items": [{"name": "Thing", "price": "10"}]}).json()
    assert got["verdict"] == "stop"


def test_a_page_read_is_remembered_judged_and_audited(client):
    scrape = {"url": "https://shop.test/p/kettle?id=7", "title": "Waterproof kettle",
              "product_name": "Kettle", "fields": {"ld:price": "49,90", "ld:priceCurrency": "EUR",
                                                    "ld:listPrice": "99,90", "ld:ratingValue": "5",
                                                    "ld:reviewCount": "4"},
              "origin": "extension"}
    client.put("/api/buyer/profile", json={"budget": {"max": 30, "currency": "EUR"}})
    got = client.post("/api/buyer/page", json=scrape).json()
    assert got["price"]["verdict"] == "first" and got["price"]["price"] == 49.9
    assert got["price"]["claimed_pct"] == 50 and got["price"]["discount"] == "unknown"
    assert got["audit"]["reviews"]["doubtful"] is True
    assert got["fit"]["breaks"] == ["budget"] and got["profile"] is True
    again = client.post("/api/buyer/page", json=scrape).json()
    assert len(again["price"]["series"]) == 1  # the same price inside hours is one sighting


def test_a_page_with_no_price_has_no_price_block(client):
    scrape = {"url": "https://shop.test/p/x", "title": "Thing", "fields": {"ld:name": "Thing"},
              "origin": "extension"}
    got = client.post("/api/buyer/page", json=scrape).json()
    assert got["price"] is None and got["fit"] is None and got["profile"] is False


def test_the_reader_is_told_what_is_kept_and_can_forget_each_part(client):
    client.put("/api/buyer/profile", json={"must": ["usb-c"]})
    client.post("/api/buyer/purchases", json={"name": "Kettle"})
    conn = rows(client)
    pricewatch.record(conn, "https://s.test/p/1", "Kettle", {"price": 20, "currency": "EUR"})
    pricewatch.watch(conn, "https://s.test/p/1", "Kettle", target=10)
    conn.close()
    kept = client.get("/api/buyer/privacy").json()
    assert (kept["profile"], kept["purchases"], kept["prices"], kept["watches"]) == (1, 1, 1, 1)
    assert kept["leaves_this_computer"] is False and kept["where"].endswith("app.sqlite")
    assert client.delete("/api/buyer/privacy/prices").json()["rows"] == 1
    assert client.get("/api/buyer/privacy").json()["prices"] == 0
    assert client.get("/api/buyer/profile").json()["empty"] is False
    assert client.delete("/api/buyer/privacy/everything").json()["rows"] >= 3
    after = client.get("/api/buyer/privacy").json()
    assert (after["profile"], after["purchases"], after["watches"]) == (0, 0, 0)
    assert client.delete("/api/buyer/privacy/nonsense").status_code == 404


# ── the relay, through the engine's own routes ──────────────────────────

@pytest.fixture
def relay_http(tmp_path, monkeypatch):
    import socket

    from kriko_cloud.app import create_app as create_relay
    from kriko_cloud.settings import Settings as RelaySettings

    from app import cloud

    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))] if host.endswith(".test")
        else real(host, port, *a, **k))
    app = create_relay(RelaySettings(db_path=tmp_path / "relay.sqlite", secret="s", registrations_per_hour=50))
    with TestClient(app) as relay:
        def http(method, url, data, headers):
            path = "/" + url.split("//", 1)[1].split("/", 1)[1]
            reply = relay.request(method, path, content=data, headers=headers)
            return reply.status_code, dict(reply.headers), reply.content

        monkeypatch.setattr(cloud, "_urllib", http)
        yield relay


def test_not_paired_is_the_ordinary_state_and_says_nothing_leaves(client):
    got = client.get("/api/cloud").json()
    assert got["connected"] is False
    assert client.get("/api/buyer/privacy").json()["leaves_this_computer"] is False
    assert client.get("/api/cloud/pairing").status_code == 422
    assert client.post("/api/cloud/sync").status_code == 422
    assert client.post("/api/cloud/watches/x", json={"on": True}).status_code == 422


def test_connecting_pairing_a_phone_and_watching_in_the_cloud(client, relay_http):
    bad = client.post("/api/cloud/connect", json={"server_url": "http://relay.example"})
    assert bad.status_code == 422 and "https" in bad.json()["detail"]
    got = client.post("/api/cloud/connect", json={"server_url": "http://127.0.0.1:8080", "private_labels": True}).json()
    assert got["connected"] is True and got["private_labels"] is True
    assert "code" not in got and "key" not in got, "the key is only ever returned on request"
    pairing = client.get("/api/cloud/pairing").json()
    assert pairing["code"].startswith("kriko-pair:") and pairing["topic"] == got["topic"]
    privacy = client.get("/api/buyer/privacy").json()
    assert privacy["leaves_this_computer"] is True and "sealed" in privacy["note"]

    made = client.post("/api/prices/watches", json={"url": "https://shop.test/p/kettle", "name": "Kettle",
                                                    "target": 30, "cloud": True}).json()
    assert made["cloud"] == 1
    with relay_http.app.state.db.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 1
    off = client.post(f"/api/cloud/watches/{made['watch_id']}", json={"on": False}).json()
    assert off["cloud"] == 0 and off["synced"] is True
    with relay_http.app.state.db.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 0
    assert client.post("/api/cloud/watches/nope", json={"on": False}).status_code == 404
    assert client.post("/api/cloud/sync").json()["watches"]["watching"] == 0
    assert client.delete("/api/cloud").json()["connected"] is False
    assert client.get("/api/buyer/privacy").json()["leaves_this_computer"] is False


def test_a_cloud_watch_needs_a_relay_and_a_relay_that_is_down_is_a_bad_gateway(client, monkeypatch):
    assert client.post("/api/prices/watches", json={"url": "https://shop.test/p/1", "cloud": True}).status_code == 422
    from app import cloud

    def down(*_):
        raise cloud.RelayError("the relay does not answer")

    monkeypatch.setattr(cloud, "_urllib", down)
    got = client.post("/api/cloud/connect", json={"server_url": "https://relay.example"})
    assert got.status_code == 502 and "does not answer" in got.json()["detail"]


def test_the_page_block_says_whether_a_relay_is_connected(client, relay_http):
    scrape = {"url": "https://shop.test/p/x", "title": "Thing", "fields": {}, "origin": "extension"}
    assert client.post("/api/buyer/page", json=scrape).json()["cloud"] == {"connected": False}
    client.post("/api/cloud/connect", json={"server_url": "http://127.0.0.1:8080"})
    assert client.post("/api/buyer/page", json=scrape).json()["cloud"] == {"connected": True}
