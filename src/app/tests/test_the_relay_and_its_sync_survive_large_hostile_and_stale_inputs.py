"""Regressions from the 0.2.6 bug hunt: the relay's limits and isolation, and a sync that finishes."""

import socket
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import buyer, cloud, pricewatch
from app.web import state
from kriko_cloud import safefetch, watcher
from kriko_cloud.app import create_app
from kriko_cloud.settings import Settings

SETUP = "open-sesame"
SERVER = "http://127.0.0.1:8080"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
PAGE = ('<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":"%s",'
        '"priceCurrency":"EUR"}}</script>')


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host.endswith(".test") and not host.startswith("dead"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        if host.startswith("dead"):
            raise socket.gaierror("no such host")
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture
def relay(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "relay.sqlite", secret="s", setup=SETUP))
    with TestClient(app) as client:
        client.relay = app
        yield client


@pytest.fixture
def web(relay):
    def http(method, url, data, headers):
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        reply = relay.request(method, path, content=data, headers=headers)
        return reply.status_code, dict(reply.headers), reply.content
    return http


@pytest.fixture
def desk(tmp_path):
    made = []

    def make(name):
        conn = state.connect(tmp_path / f"{name}.sqlite")
        made.append(conn)
        return conn

    yield make
    for conn in made:
        conn.close()


# ── the relay ────────────────────────────────────────────────────────────

def test_a_stranger_cannot_make_the_relay_read_a_large_body(relay):
    big = b'{"url":"' + b"a" * 200_000 + b'"}'
    refused = relay.put("/v1/watch/abc", content=big, headers={"Authorization": "Bearer not-a-token"})
    assert refused.status_code == 413
    refused = relay.put("/v1/owner", content=big, headers={"Authorization": "Bearer not-a-token"})
    assert refused.status_code == 413
    # Without a declared length too: the bytes are counted as they arrive.
    chunked = relay.put("/v1/watch/abc", content=(chunk for chunk in [b"x" * 10_000] * 10),
                        headers={"Authorization": "Bearer not-a-token"})
    assert chunked.status_code == 413


def test_one_page_that_cannot_be_read_does_not_stop_the_others(relay, monkeypatch):
    web = relay
    owner = cloud.Keys(cloud.new_key())
    headers = {"Authorization": f"Bearer {owner.token}"}
    assert web.put("/v1/owner", json={"topic": owner.topic}, headers={**headers, "X-Kriko-Setup": SETUP}).status_code == 200
    for wid, url in (("a", "http://bad.test/p"), ("b", "http://good.test/p")):
        assert web.put(f"/v1/watch/{wid}", json={"url": url, "target": 50}, headers=headers).status_code == 200

    def fetch(url):
        if "bad" in url:
            raise RuntimeError("a page that breaks the reader")
        return PAGE % "10"

    got = watcher.sweep(web.relay.state.db, fetch, lambda *a, **k: True, pause=lambda _s: None)
    assert got["read"] == 1 and got["failed"] == 1


def test_a_page_that_dribbles_is_cut_off_by_the_total_budget(monkeypatch):
    class Slow:
        def __init__(self):
            self.calls = 0

        def read(self, n):
            self.calls += 1
            import time
            time.sleep(0.05)
            return b"x"

    monkeypatch.setattr(safefetch, "BUDGET", 0.3)
    slow = Slow()
    assert 0 < len(safefetch._read(slow)) < 20 and slow.calls < 20


@pytest.mark.parametrize("address,public", [("64:ff9b::a9fe:a9fe", False), ("64:ff9b::7f00:1", False),
                                            ("64:ff9b::808:808", True), ("93.184.216.34", True),
                                            ("100.64.0.1", False)])
def test_an_address_inside_a_nat64_prefix_is_judged_by_the_address_it_holds(address, public):
    assert safefetch._public(address) is public


def test_a_setup_word_with_non_latin_letters_is_accepted(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "r.sqlite", secret="s", setup="şifre"))
    with TestClient(app) as client:
        def http(method, url, data, headers):
            # urllib sends header text as latin-1; httpx insists on ASCII unless given bytes.
            raw = {key: value.encode("latin-1") for key, value in headers.items()}
            reply = client.request(method, "/" + url.split("//", 1)[1].split("/", 1)[1], content=data, headers=raw)
            return reply.status_code, dict(reply.headers), reply.content

        conn = state.connect(tmp_path / "d.sqlite")
        try:
            assert cloud.connect(conn, SERVER, setup="şifre", http=http)
        finally:
            conn.close()


# ── the desktop's sync ───────────────────────────────────────────────────

@pytest.fixture
def paired(desk, web):
    a, b = desk("a"), desk("b")
    cloud.connect(a, SERVER, setup=SETUP, http=web)
    cloud.join(b, cloud.code_for(a), http=web)
    return a, b


def test_a_long_product_name_does_not_stop_the_sync(paired, web):
    a, _ = paired
    pricewatch.watch(a, "https://shop.test/p/77", "N" * 182, target=10, price=20, currency="EUR", cloud=True)
    got = cloud.sync(a, web)
    assert "problems" not in got and got["watches"]["watching"] == 1


def test_a_ledger_too_big_for_the_relay_is_trimmed_not_a_sync_that_never_ends(paired, web):
    a, b = paired
    for index in range(400):
        row = buyer.record_purchase(a, f"Product {index} " + "x" * 80, url="https://shop.test/p/" + "u" * 150 + str(index),
                                    price=10, when=NOW)
        buyer.answer(a, row["purchase_id"], "fine", "r" * 200, now=NOW)
    got = cloud.sync(a, web)
    assert "problems" not in got
    cloud.sync(b, web)
    assert 0 < len(buyer.purchases(b, 500)) <= 400 and len(buyer.purchases(a, 500)) == 400


def test_a_page_the_relay_refuses_blocks_neither_the_rest_nor_a_stopped_watch(paired, web):
    a, _ = paired
    good = pricewatch.watch(a, "https://good.test/p/1", "Good", target=10, price=20, currency="EUR", cloud=True)
    pricewatch.watch(a, "https://dead.test/p/1", "Dead", target=10, price=20, currency="EUR", cloud=True)
    first = cloud.sync(a, web)
    assert first["watches"]["watching"] == 1 and first["watches"]["refused"]
    pricewatch.set_cloud(a, good["watch_id"], False)
    second = cloud.sync(a, web)
    assert second["watches"]["stopped"] == 1
    assert cloud.relay_for(a, web).watches() == []


def test_forgetting_more_purchases_than_the_old_cap_keeps_every_one_forgotten(paired, web):
    a, b = paired
    for index in range(250):
        buyer.record_purchase(a, f"Item {index}", url=f"https://shop.test/p/{index}", price=5, when=NOW)
    cloud.sync(a, web)
    buyer.forget(a, "purchases")
    cloud.sync(a, web)
    assert buyer.purchases(a, 500) == []
    cloud.sync(b, web)
    cloud.sync(a, web)
    assert buyer.purchases(a, 500) == [] and buyer.purchases(b, 500) == []


def test_a_stale_tombstone_from_another_device_does_not_beat_a_newer_one(desk):
    conn = desk("solo")
    local = {"watches": [{"product_key": "shop.test/p/1", "url": "https://shop.test/p/1", "name": "K", "currency": "EUR",
                          "target": 1, "drop_pct": None, "started_price": 2, "cloud": 0,
                          "updated_at": "2026-10-19T03:00:00.000000+00:00"}],
             "deleted": [{"key": "shop.test/p/1", "at": "2026-10-19T05:00:00.000000+00:00"}]}
    remote = {"watches": [], "deleted": [{"key": "shop.test/p/1", "at": "2026-10-19T02:00:00.000000+00:00"}]}
    merged = cloud._watches_merge(conn, local, remote)
    assert pricewatch.watches(conn) == [] and merged["watches"] == []
    assert merged["deleted"] == [{"key": "shop.test/p/1", "at": "2026-10-19T05:00:00.000000+00:00"}]
