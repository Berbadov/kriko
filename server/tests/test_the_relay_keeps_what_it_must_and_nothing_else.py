"""The relay: ciphertext it cannot read, pages it hashes, watches it reads once, pushes without links."""

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


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in HOSTS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (HOSTS[host], port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def credentials():
    group = secrets.token_hex(16)
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    topic = "kriko-" + secrets.token_hex(16)
    return group, {"Authorization": f"Bearer {token}"}, topic


@pytest.fixture
def relay(tmp_path):
    settings = Settings(db_path=tmp_path / "relay.sqlite", secret="test-secret", registrations_per_hour=5,
                        max_watches_per_group=3, max_blob_bytes=1000)
    app = create_app(settings)
    with TestClient(app) as client:
        client.relay = app
        yield client


def joined(relay):
    group, headers, topic = credentials()
    assert relay.put(f"/v1/g/{group}", json={"topic": topic}, headers=headers).json() == {"created": True}
    return group, headers, topic


# ── groups ──────────────────────────────────────────────────────────────

def test_a_group_is_made_once_and_belongs_to_whoever_holds_its_token(relay):
    group, headers, topic = credentials()
    assert relay.put(f"/v1/g/{group}", json={"topic": topic}, headers=headers).json()["created"] is True
    assert relay.put(f"/v1/g/{group}", json={}, headers=headers).json()["created"] is False
    _, other, _ = credentials()
    assert relay.put(f"/v1/g/{group}", json={}, headers=other).status_code == 403


@pytest.mark.parametrize("header", [None, "Bearer", "Bearer short", "Basic abc"])
def test_a_request_without_a_real_token_is_refused(relay, header):
    group = secrets.token_hex(16)
    headers = {"Authorization": header} if header else {}
    assert relay.put(f"/v1/g/{group}", json={}, headers=headers).status_code == 401


def test_a_group_id_that_is_not_one_is_not_found(relay):
    _, headers, _ = credentials()
    assert relay.put("/v1/g/not-a-group", json={}, headers=headers).status_code == 404


def test_a_topic_that_is_not_a_kriko_topic_is_refused(relay):
    group, headers, _ = credentials()
    assert relay.put(f"/v1/g/{group}", json={"topic": "someone-elses-topic"}, headers=headers).status_code == 422


def test_new_groups_from_one_address_are_limited(relay):
    codes = []
    for _ in range(7):
        group, headers, _ = credentials()
        codes.append(relay.put(f"/v1/g/{group}", json={}, headers=headers).status_code)
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_a_group_can_forget_itself_and_all_it_watched(relay):
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/w1", json={"url": "https://shop.test/p/1", "target": 5}, headers=headers)
    relay.put(f"/v1/g/{group}/blob/profile", content=b"sealed", headers=headers)
    assert relay.delete(f"/v1/g/{group}", headers=headers).json() == {"forgotten": True}
    assert relay.get(f"/v1/g/{group}/blob/profile", headers=headers).status_code == 403
    with relay.relay.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


# ── blobs: ciphertext, stored as bytes ───────────────────────────────────

def test_a_blob_is_bytes_in_and_the_same_bytes_out_with_a_version(relay):
    group, headers, _ = joined(relay)
    sealed = secrets.token_bytes(200)
    assert relay.put(f"/v1/g/{group}/blob/profile", content=sealed, headers=headers).json() == {"version": 1}
    got = relay.get(f"/v1/g/{group}/blob/profile", headers=headers)
    assert got.content == sealed and got.headers["X-Kriko-Version"] == "1"
    assert relay.put(f"/v1/g/{group}/blob/profile", content=b"x", headers=headers).json() == {"version": 2}


def test_a_write_that_did_not_see_the_latest_version_is_refused(relay):
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/blob/ledger", content=b"one", headers=headers)
    relay.put(f"/v1/g/{group}/blob/ledger", content=b"two", headers={**headers, "X-Kriko-Expect": "1"})
    stale = relay.put(f"/v1/g/{group}/blob/ledger", content=b"three", headers={**headers, "X-Kriko-Expect": "1"})
    assert stale.status_code == 409
    assert relay.get(f"/v1/g/{group}/blob/ledger", headers=headers).content == b"two"
    fresh = relay.put(f"/v1/g/{group}/blob/other", content=b"x", headers={**headers, "X-Kriko-Expect": "0"})
    assert fresh.json() == {"version": 1}


def test_a_blob_is_bounded_and_named_plainly_and_not_shared_between_groups(relay):
    group, headers, _ = joined(relay)
    assert relay.put(f"/v1/g/{group}/blob/big", content=b"x" * 1001, headers=headers).status_code == 413
    assert relay.put(f"/v1/g/{group}/blob/Bad..Name", content=b"x", headers=headers).status_code == 404
    other, other_headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/blob/profile", content=b"mine", headers=headers)
    assert relay.get(f"/v1/g/{group}/blob/profile", headers=other_headers).status_code == 403
    assert relay.get(f"/v1/g/{other}/blob/profile", headers=other_headers).status_code == 404


def test_a_group_may_keep_only_a_few_blobs(relay):
    group, headers, _ = joined(relay)
    codes = [relay.put(f"/v1/g/{group}/blob/b{n}", content=b"x", headers=headers).status_code for n in range(10)]
    assert codes.count(200) == storage.MAX_BLOBS_PER_GROUP and 507 in codes


# ── watches: the one thing the relay must be told ────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://local.test/",
    "http://internal.test/p", "file:///etc/passwd", "ftp://shop.test/x", "https://user:pw@shop.test/p",
    "https://shop.test:8000/p", "https:///nohost", "http://10.0.0.1/",
])
def test_the_relay_will_not_watch_an_address_that_is_not_on_the_public_web(relay, url):
    group, headers, _ = joined(relay)
    got = relay.put(f"/v1/g/{group}/watch/w1", json={"url": url}, headers=headers)
    assert got.status_code == 422, url


def test_an_address_is_sealed_at_rest_and_indexed_by_its_hash(relay):
    group, headers, _ = joined(relay)
    url = "https://shop.test/p/secret-product?id=7&utm_source=ad"
    got = relay.put(f"/v1/g/{group}/watch/w1", json={"url": url, "label": "Kettle", "target": 30}, headers=headers)
    assert got.status_code == 200
    page = got.json()["page"]
    assert page == storage.url_hash("https://shop.test/p/secret-product?id=7")
    with relay.relay.state.db.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw = relay.relay.state.db.path.read_bytes()
    assert len(raw) > 0
    with relay.relay.state.db.connect() as conn:
        sealed = conn.execute("SELECT url_sealed FROM pages").fetchone()[0]
    assert b"secret-product" not in bytes(sealed) and b"secret-product" not in raw
    assert relay.relay.state.db.unseal(sealed) == "https://shop.test/p/secret-product?id=7"


def test_a_page_many_groups_watch_is_one_page_and_goes_when_the_last_stops(relay):
    url = "https://shop.test/p/1"
    mine, mine_h, _ = joined(relay)
    yours, yours_h, _ = joined(relay)
    relay.put(f"/v1/g/{mine}/watch/a", json={"url": url, "target": 10}, headers=mine_h)
    relay.put(f"/v1/g/{yours}/watch/b", json={"url": url + "?utm_x=1", "target": 20}, headers=yours_h)
    with relay.relay.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    relay.delete(f"/v1/g/{mine}/watch/a", headers=mine_h)
    with relay.relay.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
    relay.delete(f"/v1/g/{yours}/watch/b", headers=yours_h)
    with relay.relay.state.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
    assert relay.delete(f"/v1/g/{yours}/watch/b", headers=yours_h).status_code == 404


def test_a_group_may_watch_only_so_many_pages(relay):
    group, headers, _ = joined(relay)
    codes = [relay.put(f"/v1/g/{group}/watch/w{n}", json={"url": f"https://shop.test/p/{n}"}, headers=headers)
             .status_code for n in range(5)]
    assert codes == [200, 200, 200, 507, 507]
    # Changing one that exists is not a new one.
    assert relay.put(f"/v1/g/{group}/watch/w1", json={"url": "https://shop.test/p/1", "target": 3},
                     headers=headers).status_code == 200


def test_a_watch_listing_never_returns_an_address(relay):
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/w1", json={"url": "https://shop.test/p/hidden", "label": "Kettle"}, headers=headers)
    body = relay.get(f"/v1/g/{group}/watches", headers=headers).text
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


def test_a_shared_page_is_fetched_once_and_each_group_hears_by_its_own_terms(relay):
    url = "https://shop.test/p/kettle"
    mine, mine_h, mine_topic = joined(relay)
    yours, yours_h, yours_topic = joined(relay)
    relay.put(f"/v1/g/{mine}/watch/a", json={"url": url, "label": "Kettle", "target": 50, "currency": "EUR"},
              headers=mine_h)
    relay.put(f"/v1/g/{yours}/watch/b", json={"url": url, "label": "My kettle", "target": 30, "currency": "EUR"},
              headers=yours_h)
    world = World({url: "45.00"})
    assert sweep(relay, world, NOW) == {"read": 1, "failed": 0, "alerts": 1}
    assert world.fetched == [url]
    assert world.pushed == [("https://ntfy.example", mine_topic, "Price dropped", "Kettle: 45 EUR")]
    assert relay.get(f"/v1/g/{mine}/alerts", headers=mine_h).json()["items"][0]["price"] == 45
    assert relay.get(f"/v1/g/{yours}/alerts", headers=yours_h).json()["items"] == []


def test_a_push_carries_a_label_and_a_price_and_never_an_address(relay):
    url = "https://shop.test/p/kettle-with-a-telling-name"
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/a", json={"url": url, "target": 50}, headers=headers)
    world = World({url: "40"})
    sweep(relay, world, NOW)
    assert world.pushed and "telling-name" not in repr(world.pushed) and "shop.test" not in repr(world.pushed)


def test_the_same_price_is_not_announced_twice_but_a_lower_one_is(relay):
    url = "https://shop.test/p/kettle"
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/a", json={"url": url, "target": 50}, headers=headers)
    world = World({url: "45"})
    sweep(relay, world, NOW)
    assert sweep(relay, world, NOW + timedelta(hours=7))["alerts"] == 0
    world.prices[url] = "40"
    assert sweep(relay, world, NOW + timedelta(hours=14))["alerts"] == 1
    assert [a["price"] for a in relay.get(f"/v1/g/{group}/alerts", headers=headers).json()["items"]] == [45, 40]
    assert relay.get(f"/v1/g/{group}/alerts?after=1", headers=headers).json()["items"][0]["price"] == 40


def test_a_page_is_not_read_again_before_it_is_due_and_failures_back_off(relay):
    url = "https://shop.test/p/unreadable"
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/a", json={"url": url, "target": 50}, headers=headers)
    world = World({})
    assert sweep(relay, world, NOW)["failed"] == 1
    assert sweep(relay, world, NOW + timedelta(hours=1)) == {"read": 0, "failed": 0, "alerts": 0}
    assert sweep(relay, world, NOW + timedelta(hours=7)) == {"read": 0, "failed": 0, "alerts": 0}, \
        "after one failure the wait is doubled"
    assert sweep(relay, world, NOW + timedelta(hours=13))["failed"] == 1
    assert len(world.fetched) == 2


def test_a_page_in_another_currency_is_not_compared_to_the_target(relay):
    url = "https://shop.test/p/kettle"
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/a", json={"url": url, "target": 50, "currency": "TRY"}, headers=headers)
    assert sweep(relay, World({url: "10"}), NOW)["alerts"] == 0


def test_a_fall_from_the_starting_price_alerts_without_a_target(relay):
    url = "https://shop.test/p/kettle"
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/a", json={"url": url, "drop_pct": 20, "started_price": 100}, headers=headers)
    assert sweep(relay, World({url: "90"}), NOW)["alerts"] == 0
    assert sweep(relay, World({url: "75"}), NOW + timedelta(hours=7))["alerts"] == 1


def test_a_group_nobody_has_touched_is_forgotten(relay):
    group, headers, _ = joined(relay)
    relay.put(f"/v1/g/{group}/watch/a", json={"url": "https://shop.test/p/1"}, headers=headers)
    db = relay.relay.state.db
    assert db.forget_idle(180) == 0
    assert db.forget_idle(180, NOW + timedelta(days=400)) == 1
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


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
