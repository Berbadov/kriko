"""Pairing, sealed sync between two devices, cloud watches and the alerts they raise, against a real relay."""

import socket
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import buyer, cloud, pricewatch
from app.web import state
from kriko_cloud import watcher
from kriko_cloud.app import create_app
from kriko_cloud.settings import Settings

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
SERVER = "http://127.0.0.1:8080"
PAGE = ('<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":"%s",'
        '"priceCurrency":"EUR"}}</script>')


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host.endswith(".test"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture
def relay(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "relay.sqlite", secret="s", registrations_per_hour=50))
    with TestClient(app) as client:
        client.relay = app
        yield client


def http_for(client):
    def http(method, url, data, headers):
        path = "/" + url.split("//", 1)[1].split("/", 1)[1]
        reply = client.request(method, path, content=data, headers=headers)
        return reply.status_code, dict(reply.headers), reply.content
    return http


@pytest.fixture
def web(relay):
    return http_for(relay)


@pytest.fixture
def desk(tmp_path):
    """A device: its own app.sqlite."""
    made = []

    def make(name):
        conn = state.connect(tmp_path / f"{name}.sqlite")
        made.append(conn)
        return conn

    yield make
    for conn in made:
        conn.close()


# ── keys and sealing ────────────────────────────────────────────────────

def test_everything_is_derived_from_the_one_key_and_never_equal_to_it():
    key = cloud.new_key()
    keys = cloud.Keys(key)
    again = cloud.Keys(key)
    assert (keys.group, keys.token, keys.topic) == (again.group, again.token, again.topic)
    assert len(keys.group) == 32 and keys.topic.startswith("kriko-") and len(keys.topic) == 6 + 32
    assert key not in (keys.group, keys.token, keys.topic)
    other = cloud.Keys(cloud.new_key())
    assert {other.group, other.token} & {keys.group, keys.token} == set()


def test_a_sealed_blob_opens_only_with_its_key_and_its_name():
    keys = cloud.Keys(cloud.new_key())
    sealed = keys.seal("profile", {"about": "secret words"})
    assert b"secret words" not in sealed
    assert keys.open("profile", sealed) == {"about": "secret words"}
    with pytest.raises(ValueError):
        keys.open("ledger", sealed)
    with pytest.raises(ValueError):
        cloud.Keys(cloud.new_key()).open("profile", sealed)
    with pytest.raises(ValueError):
        keys.open("profile", sealed[:-1] + bytes([sealed[-1] ^ 1]))
    with pytest.raises(ValueError):
        keys.open("profile", b"not sealed")
    assert keys.seal("profile", {"a": 1}) != keys.seal("profile", {"a": 1}), "a fresh nonce each time"


def test_a_key_that_is_not_32_bytes_is_refused():
    with pytest.raises(ValueError):
        cloud.Keys("short")


def test_a_pairing_code_round_trips_and_a_bad_one_is_refused():
    key = cloud.new_key()
    code = cloud.pairing_code("https://relay.example", key)
    assert cloud.parse_code(code) == ("https://relay.example", key)
    for bad in ("", "nonsense", "kriko-pair:abc", f"kriko-pair:{'x'}:{key}", "other:aaa:bbb"):
        with pytest.raises(ValueError):
            cloud.parse_code(bad)


@pytest.mark.parametrize("server", ["http://relay.example", "ftp://relay.example", "https://u:p@relay.example",
                                    "relay.example", ""])
def test_a_token_is_never_sent_in_the_clear_or_to_a_nonsense_address(server):
    with pytest.raises(ValueError):
        cloud.secure(server)


def test_https_and_a_loopback_relay_are_accepted():
    assert cloud.secure("https://relay.example/") == "https://relay.example"
    assert cloud.secure("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert cloud.secure("http://localhost:8080/base/") == "http://localhost:8080/base"


# ── connecting ──────────────────────────────────────────────────────────

def test_connecting_makes_a_group_the_relay_knows_only_by_id(desk, web, relay):
    conn = desk("a")
    assert cloud.status(conn)["connected"] is False
    got = cloud.connect(conn, SERVER, http=web)
    assert got["connected"] is True and got["server"] == SERVER and len(got["group"]) == 8
    with relay.relay.state.db.connect() as db:
        row = db.execute("SELECT group_id, topic FROM groups").fetchone()
    code = cloud.code_for(conn)
    key = cloud.parse_code(code)[1]
    assert row["group_id"] == cloud.Keys(key).group and row["topic"] == got["topic"]
    assert key not in repr(dict(row))


def test_joining_with_a_code_lands_in_the_same_group(desk, web, relay):
    a, b = desk("a"), desk("b")
    cloud.connect(a, SERVER, http=web)
    cloud.join(b, cloud.code_for(a), http=web)
    assert cloud.status(a)["group"] == cloud.status(b)["group"]
    with relay.relay.state.db.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 1


def test_disconnecting_forgets_the_group_there_and_the_key_here(desk, web, relay):
    conn = desk("a")
    cloud.connect(conn, SERVER, http=web)
    cloud.disconnect(conn, http=web)
    assert cloud.status(conn)["connected"] is False
    with relay.relay.state.db.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 0
    with pytest.raises(ValueError):
        cloud.code_for(conn)


def test_a_relay_that_does_not_answer_is_a_relay_error_and_a_quiet_no_op_for_a_clock(desk, web):
    conn = desk("a")
    cloud.connect(conn, SERVER, http=web)

    def down(*_):
        raise cloud.RelayError("the relay does not answer")

    with pytest.raises(cloud.RelayError):
        cloud.sync(conn, down)
    assert cloud.sync_quietly(conn, down) is None
    assert cloud.sync_quietly(desk("never-paired"), down) is None


# ── sync: two devices, one sealed state ─────────────────────────────────

def paired(desk, web):
    a, b = desk("a"), desk("b")
    cloud.connect(a, SERVER, http=web)
    cloud.join(b, cloud.code_for(a), http=web)
    return a, b


def test_a_profile_made_on_one_device_arrives_on_the_other_and_the_relay_cannot_read_it(desk, web, relay):
    a, b = paired(desk, web)
    buyer.save(a, {"about": "I carry it daily", "avoid": ["Acme"], "budget": {"max": 900, "currency": "eur"}})
    cloud.sync(a, web)
    cloud.sync(b, web)
    assert buyer.read(b)["avoid"] == ["Acme"] and buyer.read(b)["budget"]["max"] == 900
    with relay.relay.state.db.connect() as db:
        stored = db.execute("SELECT body FROM blobs WHERE name = 'profile'").fetchone()[0]
    assert b"Acme" not in bytes(stored) and b"carry" not in bytes(stored)


def test_the_later_edit_wins_on_both(desk, web):
    a, b = paired(desk, web)
    buyer.save(a, {"about": "first"})
    cloud.sync(a, web)
    cloud.sync(b, web)
    buyer.save(b, {"about": "second"})
    cloud.sync(b, web)
    cloud.sync(a, web)
    assert buyer.read(a)["about"] == "second" and buyer.read(b)["about"] == "second"


def test_forgetting_the_profile_on_one_device_empties_the_other(desk, web):
    a, b = paired(desk, web)
    buyer.save(a, {"about": "mine"})
    cloud.sync(a, web)
    cloud.sync(b, web)
    buyer.forget(b, "profile")
    cloud.sync(b, web)
    cloud.sync(a, web)
    assert buyer.is_empty(buyer.read(a))


def test_a_purchase_and_its_answer_travel_and_a_deletion_does_not_come_back(desk, web):
    a, b = paired(desk, web)
    bought = buyer.record_purchase(a, "Kettle", url="https://shop.test/k", when=NOW)
    cloud.sync(a, web)
    cloud.sync(b, web)
    assert [p["name"] for p in buyer.purchases(b)] == ["Kettle"]
    buyer.answer(b, bought["purchase_id"], "regret", "lid cracked", now=NOW + timedelta(days=30))
    cloud.sync(b, web)
    cloud.sync(a, web)
    assert buyer.purchases(a)[0]["verdict"] == "regret" and buyer.purchases(a)[0]["reason"] == "lid cracked"
    buyer.forget_purchase(a, bought["purchase_id"])
    cloud.sync(a, web)
    cloud.sync(b, web)
    assert buyer.purchases(b) == []
    cloud.sync(a, web)
    assert buyer.purchases(a) == []


def test_a_watch_travels_and_a_stopped_watch_stays_stopped_everywhere(desk, web):
    a, b = paired(desk, web)
    made = pricewatch.watch(a, "https://shop.test/p/kettle", "Kettle", target=30, price=40, currency="EUR")
    cloud.sync(a, web)
    cloud.sync(b, web)
    there = pricewatch.watches(b)
    assert len(there) == 1 and there[0]["name"] == "Kettle" and there[0]["target"] == 30
    pricewatch.unwatch(a, made["watch_id"])
    cloud.sync(a, web)
    cloud.sync(b, web)
    assert pricewatch.watches(b) == []
    cloud.sync(a, web)
    assert pricewatch.watches(a) == []


def test_a_changed_target_on_one_device_reaches_the_other(desk, web):
    a, b = paired(desk, web)
    pricewatch.watch(a, "https://shop.test/p/kettle", "Kettle", target=30, now=NOW)
    cloud.sync(a, web)
    cloud.sync(b, web)
    pricewatch.watch(b, "https://shop.test/p/kettle", "", target=20, now=NOW + timedelta(hours=1))
    cloud.sync(b, web)
    cloud.sync(a, web)
    assert pricewatch.watches(a)[0]["target"] == 20


# ── cloud watches and alerts ────────────────────────────────────────────

def relay_watches(relay):
    with relay.relay.state.db.connect() as db:
        return [dict(r) for r in db.execute("SELECT w.watch_id, w.label, w.target FROM watches w")]


def test_a_page_goes_to_the_relay_only_when_that_watch_is_turned_on(desk, web, relay):
    conn = desk("a")
    cloud.connect(conn, SERVER, http=web)
    made = pricewatch.watch(conn, "https://shop.test/p/kettle", "Kettle", target=30)
    cloud.sync(conn, web)
    assert relay_watches(relay) == [], "a watch is private until the reader says otherwise"
    pricewatch.set_cloud(conn, made["watch_id"], True)
    got = cloud.sync(conn, web)
    assert got["watches"] == {"watching": 1, "stopped": 0}
    assert relay_watches(relay) == [{"watch_id": cloud.cloud_id(made["product_key"]), "label": "Kettle", "target": 30}]
    pricewatch.set_cloud(conn, made["watch_id"], False)
    assert cloud.sync(conn, web)["watches"] == {"watching": 0, "stopped": 1}
    assert relay_watches(relay) == []


def test_private_labels_tell_the_relay_a_page_but_not_its_name(desk, web, relay):
    conn = desk("a")
    cloud.connect(conn, SERVER, private_labels=True, http=web)
    made = pricewatch.watch(conn, "https://shop.test/p/kettle", "My secret hobby kit", target=30, cloud=True)
    cloud.sync(conn, web)
    assert relay_watches(relay)[0]["label"] == cloud.GENERIC_LABEL
    assert "hobby" not in repr(relay_watches(relay))
    assert made["cloud"] == 1


def test_two_devices_watching_one_page_in_the_cloud_make_one_relay_watch(desk, web, relay):
    a, b = paired(desk, web)
    pricewatch.watch(a, "https://shop.test/p/kettle", "Kettle", target=30, cloud=True)
    cloud.sync(a, web)
    cloud.sync(b, web)
    assert pricewatch.watches(b)[0]["cloud"] == 1
    cloud.sync(b, web)
    assert len(relay_watches(relay)) == 1


def sweep_relay(relay, price, at):
    pushed = []
    result = watcher.sweep(relay.relay.state.db, lambda url: PAGE % price,
                           lambda *a: pushed.append(a) or True, at=at, pause=lambda s: None)
    return result, pushed


def test_an_alert_raised_while_the_computer_was_off_arrives_as_an_ordinary_alert_once(desk, web, relay):
    conn = desk("a")
    cloud.connect(conn, SERVER, private_labels=True, http=web)
    pricewatch.watch(conn, "https://shop.test/p/kettle", "Kettle", target=50, currency="EUR", cloud=True)
    cloud.sync(conn, web)
    result, pushed = sweep_relay(relay, "42", NOW)
    assert result["alerts"] == 1
    assert pushed[0][3] == "A page you watch: 42 EUR" and "shop.test" not in repr(pushed)
    assert cloud.sync(conn, web)["alerts"] == 1
    [alert] = pricewatch.alerts(conn)
    assert alert["name"] == "Kettle" and alert["price"] == 42 and alert["url"] == "https://shop.test/p/kettle"
    assert cloud.sync(conn, web)["alerts"] == 0, "the cursor moved on"
    assert len(pricewatch.alerts(conn, unread_only=False)) == 1


def test_an_alert_for_a_watch_that_is_gone_is_dropped(desk, web, relay):
    conn = desk("a")
    cloud.connect(conn, SERVER, http=web)
    made = pricewatch.watch(conn, "https://shop.test/p/kettle", "Kettle", target=50, cloud=True)
    cloud.sync(conn, web)
    sweep_relay(relay, "42", NOW)
    pricewatch.unwatch(conn, made["watch_id"])
    cloud.sync(conn, web)
    assert pricewatch.alerts(conn) == []


def test_the_price_clock_syncs_a_paired_reader_and_leaves_an_unpaired_one_alone(desk, web, tmp_path):
    from app import pricescheduler

    path = tmp_path / "clock.sqlite"
    conn = state.connect(path)
    calls = []
    sweeper = pricescheduler.Sweeper(path, lambda: "", sync=lambda c: calls.append(1))
    sweeper.tick()
    assert calls == [1]
    conn.close()
