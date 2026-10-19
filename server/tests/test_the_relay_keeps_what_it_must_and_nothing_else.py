"""The relay: one reader, ciphertext it cannot read, watches it reads, pushes without links."""

import base64
import secrets
import socket
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kriko_cloud import safefetch, store as storage, watcher
from kriko_cloud.app import create_app
from kriko_cloud.settings import Settings

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
PUBLIC = "93.184.216.34"
HOSTS = {"shop.test": PUBLIC, "other.test": PUBLIC, "internal.test": "10.0.0.5", "local.test": "127.0.0.1"}
SETUP = "open-sesame"


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in HOSTS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (HOSTS[host], port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def owner():
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    return {"Authorization": f"Bearer {token}"}, "kriko-" + secrets.token_hex(16)


@pytest.fixture
def relay(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "relay.sqlite", secret="test-secret", setup=SETUP,
                              max_watches=3, max_blob_bytes=1000))
    with TestClient(app) as client:
        client.relay = app
        yield client


def claimed(relay):
    headers, topic = owner()
    got = relay.put("/v1/owner", json={"topic": topic}, headers={**headers, "X-Kriko-Setup": SETUP})
    assert got.json() == {"claimed": True}
    return headers, topic


# ── the owner ───────────────────────────────────────────────────────────

def test_the_first_device_with_the_setup_word_claims_the_relay_and_is_known_again_without_it(relay):
    headers, topic = owner()
    assert relay.put("/v1/owner", json={"topic": topic}, headers={**headers, "X-Kriko-Setup": SETUP}).json() == {
        "claimed": True}
    assert relay.put("/v1/owner", json={}, headers=headers).json() == {"claimed": False}


def test_a_stranger_who_reaches_a_fresh_relay_first_cannot_claim_it(relay):
    headers, topic = owner()
    for extra in ({}, {"X-Kriko-Setup": "guess"}):
        assert relay.put("/v1/owner", json={"topic": topic}, headers={**headers, **extra}).status_code == 403
    with relay.relay.state.db.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM owner").fetchone()[0] == 0


def test_a_relay_with_no_setup_word_cannot_be_claimed_at_all(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "r.sqlite", secret="s", setup=""))
    with TestClient(app) as client:
        headers, topic = owner()
        got = client.put("/v1/owner", json={"topic": topic}, headers={**headers, "X-Kriko-Setup": ""})
        assert got.status_code == 403 and "no setup word" in got.json()["detail"]


def test_once_claimed_it_belongs_to_one_reader(relay):
    claimed(relay)
    other, topic = owner()
    got = relay.put("/v1/owner", json={"topic": topic}, headers={**other, "X-Kriko-Setup": SETUP})
    assert got.status_code == 403 and "someone else" in got.json()["detail"]


@pytest.mark.parametrize("header", [None, "Bearer", "Bearer short", "Basic abc"])
def test_a_request_without_a_real_token_is_refused(relay, header):
    headers = {"Authorization": header} if header else {}
    assert relay.put("/v1/owner", json={}, headers=headers).status_code == 401
    assert relay.get("/v1/watches", headers=headers).status_code == 401


def test_every_route_but_health_wants_the_owner(relay):
    claimed(relay)
    other, _ = owner()
    for method, path in (("get", "/v1/watches"), ("get", "/v1/alerts"), ("get", "/v1/blob/profile"),
                         ("delete", "/v1/owner")):
        assert getattr(relay, method)(path, headers=other).status_code == 403, path
    assert relay.get("/v1/health").json()["ok"] is True


def test_a_topic_that_is_not_a_kriko_topic_is_refused(relay):
    headers, _ = owner()
    got = relay.put("/v1/owner", json={"topic": "someone-elses"}, headers={**headers, "X-Kriko-Setup": SETUP})
    assert got.status_code == 422


def test_releasing_forgets_everything_and_frees_the_relay(relay):
    headers, _ = claimed(relay)
    relay.put("/v1/watch/w1", json={"url": "https://shop.test/p/1", "target": 5}, headers=headers)
    relay.put("/v1/blob/profile", content=b"sealed", headers=headers)
    assert relay.delete("/v1/owner", headers=headers).json() == {"released": True}
    with relay.relay.state.db.connect() as conn:
        counts = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("owner", "watches", "blobs")]
    assert counts == [0, 0, 0]
    claimed(relay)  # free for the next owner


# ── blobs: ciphertext, stored as bytes ───────────────────────────────────

def test_a_blob_is_bytes_in_and_the_same_bytes_out_with_a_version(relay):
    headers, _ = claimed(relay)
    sealed = secrets.token_bytes(200)
    assert relay.put("/v1/blob/profile", content=sealed, headers=headers).json() == {"version": 1}
    got = relay.get("/v1/blob/profile", headers=headers)
    assert got.content == sealed and got.headers["X-Kriko-Version"] == "1"
    assert relay.put("/v1/blob/profile", content=b"x", headers=headers).json() == {"version": 2}


def test_a_write_that_did_not_see_the_latest_version_is_refused(relay):
    headers, _ = claimed(relay)
    relay.put("/v1/blob/ledger", content=b"one", headers=headers)
    relay.put("/v1/blob/ledger", content=b"two", headers={**headers, "X-Kriko-Expect": "1"})
    stale = relay.put("/v1/blob/ledger", content=b"three", headers={**headers, "X-Kriko-Expect": "1"})
    assert stale.status_code == 409
    assert relay.get("/v1/blob/ledger", headers=headers).content == b"two"
    assert relay.put("/v1/blob/other", content=b"x", headers={**headers, "X-Kriko-Expect": "0"}).json() == {
        "version": 1}


def test_a_blob_is_bounded_and_named_plainly(relay):
    headers, _ = claimed(relay)
    assert relay.put("/v1/blob/big", content=b"x" * 1001, headers=headers).status_code == 413
    assert relay.put("/v1/blob/Bad..Name", content=b"x", headers=headers).status_code == 404
    assert relay.get("/v1/blob/missing", headers=headers).status_code == 404


def test_only_a_few_blobs_may_be_kept(relay):
    headers, _ = claimed(relay)
    codes = [relay.put(f"/v1/blob/b{n}", content=b"x", headers=headers).status_code for n in range(10)]
    assert codes.count(200) == storage.MAX_BLOBS and 507 in codes


# ── watches: the one thing the relay must be told ────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://local.test/",
    "http://internal.test/p", "file:///etc/passwd", "ftp://shop.test/x", "https://user:pw@shop.test/p",
    "https://shop.test:8000/p", "https:///nohost", "http://10.0.0.1/",
])
def test_the_relay_will_not_watch_an_address_that_is_not_on_the_public_web(relay, url):
    headers, _ = claimed(relay)
    assert relay.put("/v1/watch/w1", json={"url": url}, headers=headers).status_code == 422, url


def test_an_address_is_sealed_at_rest_and_indexed_by_its_hash(relay):
    headers, _ = claimed(relay)
    url = "https://shop.test/p/secret-product?id=7&utm_source=ad"
    got = relay.put("/v1/watch/w1", json={"url": url, "label": "Kettle", "target": 30}, headers=headers)
    assert got.status_code == 200
    assert got.json()["page"] == storage.url_hash("https://shop.test/p/secret-product?id=7")
    with relay.relay.state.db.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw = relay.relay.state.db.path.read_bytes()
    assert len(raw) > 0 and b"secret-product" not in raw
    with relay.relay.state.db.connect() as conn:
        sealed = conn.execute("SELECT url_sealed FROM watches").fetchone()[0]
    assert relay.relay.state.db.unseal(sealed) == "https://shop.test/p/secret-product?id=7"


def test_a_watch_can_be_changed_replaced_and_stopped(relay):
    headers, _ = claimed(relay)
    relay.put("/v1/watch/w1", json={"url": "https://shop.test/p/1", "target": 10}, headers=headers)
    relay.put("/v1/watch/w1", json={"url": "https://shop.test/p/1", "target": 20}, headers=headers)
    assert [w["target"] for w in relay.get("/v1/watches", headers=headers).json()["items"]] == [20]
    relay.put("/v1/watch/w1", json={"url": "https://shop.test/p/2", "target": 5}, headers=headers)
    items = relay.get("/v1/watches", headers=headers).json()["items"]
    assert len(items) == 1 and items[0]["url_hash"] == storage.url_hash("https://shop.test/p/2")
    assert relay.delete("/v1/watch/w1", headers=headers).status_code == 200
    assert relay.delete("/v1/watch/w1", headers=headers).status_code == 404


def test_only_so_many_pages_may_be_watched(relay):
    headers, _ = claimed(relay)
    codes = [relay.put(f"/v1/watch/w{n}", json={"url": f"https://shop.test/p/{n}"}, headers=headers).status_code
             for n in range(5)]
    assert codes == [200, 200, 200, 507, 507]
    assert relay.put("/v1/watch/w1", json={"url": "https://shop.test/p/1", "target": 3}, headers=headers
                     ).status_code == 200


def test_a_watch_listing_never_returns_an_address(relay):
    headers, _ = claimed(relay)
    relay.put("/v1/watch/w1", json={"url": "https://shop.test/p/hidden", "label": "Kettle"}, headers=headers)
    body = relay.get("/v1/watches", headers=headers).text
    assert "hidden" not in body and "Kettle" in body


# ── sweeping ────────────────────────────────────────────────────────────

PAGE = ('<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":"%s",'
        '"priceCurrency":"EUR"}}</script>')


class World:
    def __init__(self, prices):
        self.prices, self.fetched, self.pushed = prices, [], []

    def fetch(self, url):
        self.fetched.append(url)
        value = self.prices.get(url.split("?")[0])
        return PAGE % value if value is not None else "<html>no price</html>"

    def push(self, base, topic, title, message):
        self.pushed.append((base, topic, title, message))
        return True


def sweep(relay, world, at):
    return watcher.sweep(relay.relay.state.db, world.fetch, world.push, at=at, pause=lambda s: None,
                         ntfy_base="https://ntfy.example")


def test_a_crossed_target_raises_one_alert_and_one_push_to_the_owners_topic(relay):
    url = "https://shop.test/p/kettle"
    headers, topic = claimed(relay)
    relay.put("/v1/watch/a", json={"url": url, "label": "Kettle", "target": 50, "currency": "EUR"}, headers=headers)
    world = World({url: "45.00"})
    assert sweep(relay, world, NOW) == {"read": 1, "failed": 0, "alerts": 1}
    assert world.pushed == [("https://ntfy.example", topic, "Price dropped", "Kettle: 45 EUR")]
    assert relay.get("/v1/alerts", headers=headers).json()["items"][0]["price"] == 45


def test_a_push_carries_a_label_and_a_price_and_never_an_address(relay):
    url = "https://shop.test/p/kettle-with-a-telling-name"
    headers, _ = claimed(relay)
    relay.put("/v1/watch/a", json={"url": url, "target": 50}, headers=headers)
    world = World({url: "40"})
    sweep(relay, world, NOW)
    assert world.pushed and "telling-name" not in repr(world.pushed) and "shop.test" not in repr(world.pushed)


def test_the_same_price_is_not_announced_twice_but_a_lower_one_is(relay):
    url = "https://shop.test/p/kettle"
    headers, _ = claimed(relay)
    relay.put("/v1/watch/a", json={"url": url, "target": 50}, headers=headers)
    world = World({url: "45"})
    sweep(relay, world, NOW)
    assert sweep(relay, world, NOW + timedelta(hours=7))["alerts"] == 0
    world.prices[url] = "40"
    assert sweep(relay, world, NOW + timedelta(hours=14))["alerts"] == 1
    assert [a["price"] for a in relay.get("/v1/alerts", headers=headers).json()["items"]] == [45, 40]
    assert relay.get("/v1/alerts?after=1", headers=headers).json()["items"][0]["price"] == 40


def test_a_page_is_not_read_again_before_it_is_due_and_failures_back_off(relay):
    url = "https://shop.test/p/unreadable"
    headers, _ = claimed(relay)
    relay.put("/v1/watch/a", json={"url": url, "target": 50}, headers=headers)
    world = World({})
    assert sweep(relay, world, NOW)["failed"] == 1
    assert sweep(relay, world, NOW + timedelta(hours=1)) == {"read": 0, "failed": 0, "alerts": 0}
    assert sweep(relay, world, NOW + timedelta(hours=7)) == {"read": 0, "failed": 0, "alerts": 0}, \
        "after one failure the wait is doubled"
    assert sweep(relay, world, NOW + timedelta(hours=13))["failed"] == 1
    assert len(world.fetched) == 2


def test_a_page_in_another_currency_is_not_compared_to_the_target(relay):
    url = "https://shop.test/p/kettle"
    headers, _ = claimed(relay)
    relay.put("/v1/watch/a", json={"url": url, "target": 50, "currency": "TRY"}, headers=headers)
    assert sweep(relay, World({url: "10"}), NOW)["alerts"] == 0


def test_a_fall_from_the_starting_price_alerts_without_a_target(relay):
    url = "https://shop.test/p/kettle"
    headers, _ = claimed(relay)
    relay.put("/v1/watch/a", json={"url": url, "drop_pct": 20, "started_price": 100}, headers=headers)
    assert sweep(relay, World({url: "90"}), NOW)["alerts"] == 0
    assert sweep(relay, World({url: "75"}), NOW + timedelta(hours=7))["alerts"] == 1


# ── the fetcher ─────────────────────────────────────────────────────────

def test_a_redirect_to_a_private_address_is_refused_too():
    import urllib.request

    handler = safefetch._Redirects()
    request = urllib.request.Request("https://shop.test/p")
    with pytest.raises(safefetch.Refused):
        handler.redirect_request(request, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/")


def test_an_unresolvable_host_is_refused_not_raised():
    assert safefetch.markup("https://does-not-resolve.invalid/") == ""
    assert safefetch.markup("http://127.0.0.1:1/") == ""
