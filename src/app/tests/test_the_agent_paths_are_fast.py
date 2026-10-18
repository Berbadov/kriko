"""What a turn pays before the model is asked, measured rather than assumed.

The reader's requirement was *"lightning fast"*, and the two costs found by
measurement were both pure overhead — work repeated that had the same answer
every time:

* `app/providers/network.py` built a fresh no-proxy opener for **every** loopback
  request. `urllib.request.build_opener` costs 15.8 ms, and every local model
  call, every OpenSERP search and every model-list probe is a loopback request:
  17.2 ms per request before, 1.4 ms after.
* `app/categorizer.catalogs` asked the store one question per pack and one per
  subject — **159 statements for twelve catalogs**, and a Quick Look reads the
  profiles twice, so 318 round trips before an agent saw a word. Now six.

Both are asserted here without a clock: a rebuilt transport is a call that
happened, and an N+1 is a statement count that grows with the data. A wall-clock
assertion on somebody else's machine is a flaky test, not a measurement —
`tools/bench_agent_planes.py` is where the seconds live.
"""

import json

import pytest

from app import categorizer
from app.providers import network
# Imported at module level on purpose: the suite-wide guard replaces
# `local_discovery.discover` in an autouse fixture, so a function-level import
# would capture the guard instead of the real discovery.
from app.providers.local_discovery import discover as real_discover
from kriko.store.db import connect


def _catalogue(store, packs: int) -> None:
    """A store with `packs` catalogs, each with terms, subjects and aliases."""
    for index in range(packs):
        pack_id = f"cat.{index:02d}"
        store.execute(
            "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
            " content_digest, enabled, installed_at, manifest_json)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (pack_id, f"Category {index:02d}", "1", 1, "2026-09-01", "d", 1,
             "2026-09-01", json.dumps({"identity_keys": {"model": ["model"]}})))
        for term in range(6):
            store.execute(
                "INSERT INTO terms (pack_id, term_id, role, label_json) VALUES (?,?,?,?)",
                (pack_id, f"term_{term:02d}",
                 "subject_kind" if term == 0 else "attribute",
                 json.dumps({"en": f"term {term}"})))
        for row in range(5):
            subject = f"s{index}_{row}"
            store.execute(
                "INSERT INTO subjects (subject_id, pack_id, kind, label) VALUES (?,?,?,?)",
                (subject, pack_id, "product", f"Product {row}"))
            for alias in range(6):
                store.execute(
                    "INSERT INTO subject_aliases (subject_id, pack_id, alias, lang, tier)"
                    " VALUES (?,?,?,?,?)", (subject, pack_id, f"alias {alias}", "en", 1))
            store.execute(
                "INSERT INTO attributes (attribute_id, pack_id, subject_id, key,"
                " value_text, is_identity) VALUES (?,?,?,?,?,?)",
                (f"a{index}_{row}", pack_id, subject, "model", "X", 1))


def _counting(monkeypatch) -> dict:
    """Count the statements `categorizer` makes through one connection."""
    counts = {"n": 0}
    real = categorizer.connect

    class Counting:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, *args, **kwargs):
            counts["n"] += 1
            return self._conn.execute(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(categorizer, "connect", lambda path: Counting(real(path)))
    return counts


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "knowledge.sqlite"


def test_a_catalogue_is_read_from_the_store_in_one_pass_not_one_query_per_row(
        tmp_path, monkeypatch):
    """The statement count must not grow with the installation."""
    counts = _counting(monkeypatch)
    counts_for = {}
    for packs in (3, 12):
        path = tmp_path / f"store-{packs}.sqlite"
        store = connect(path)
        _catalogue(store, packs)
        store.commit()
        store.close()

        counts["n"] = 0
        profiles = categorizer.catalogs(path)

        assert len(profiles) == packs
        counts_for[packs] = counts["n"]

    assert counts_for[3] == counts_for[12], (
        f"{counts_for[3]} statements for three catalogs, {counts_for[12]} for "
        "twelve: the read is per pack, not per installation")
    assert counts_for[12] < 10, (
        f"a batched read should be a handful, not {counts_for[12]}")


def test_the_batched_catalogue_read_returns_the_rows_the_store_holds(store_path):
    """Batching must not change what a profile says.

    Every bound the per-pack queries used to apply is applied here against the
    same rows: the subjects in the store's order, the first four aliases of each
    by alias, the identity keys sorted, and each pack's own terms.
    """
    store = connect(store_path)
    _catalogue(store, 2)
    store.commit()
    store.close()

    profiles = categorizer.catalogs(store_path)
    first = next(one for one in profiles if one["pack_id"] == "cat.00")

    assert first["name"] == "Category 00"
    assert [one["id"] for one in first["definition"]["kinds"]] == ["term_00"]
    assert [one["id"] for one in first["definition"]["attributes"]] == [
        f"term_{index:02d}" for index in range(1, 6)]
    assert first["definition"]["identity_keys"] == ["model"]
    examples = first["definition"]["examples"]
    assert [one["label"] for one in examples] == [f"Product {row}" for row in range(5)]
    assert examples[0]["aliases"] == [f"alias {alias}" for alias in range(4)], (
        "the store took four aliases per subject; so does this")
    assert "Category 00" in first["terms"] and "model" in first["terms"]


def test_the_readiness_question_remembers_its_answer_for_one_turn(monkeypatch):
    """Three questions, one ask. A refresh asks again."""
    from app.providers import local_discovery

    monkeypatch.setattr(local_discovery, "discover", real_discover)
    asked = {"n": 0}
    real = local_discovery._listening

    def counted(url):
        asked["n"] += 1
        return real(url)

    monkeypatch.setattr(local_discovery, "_listening", counted)
    local_discovery.forget_discovery()

    local_discovery.discover()
    after_first = asked["n"]
    assert after_first > 0, "the first question must really probe"

    local_discovery.discover()
    assert asked["n"] == after_first, "the second question re-probed the machine"

    local_discovery.forget_discovery()
    local_discovery.discover()
    assert asked["n"] > after_first, "a refresh must ask again"
    local_discovery.forget_discovery()


def test_a_loopback_request_does_not_rebuild_its_transport(monkeypatch):
    """`build_opener` is 15.8 ms of handler assembly, and a local turn makes
    dozens of loopback requests. It is built once, not once each."""
    import urllib.request

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    built = {"n": 0}
    real_build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *a, **k: built.update(n=built["n"] + 1) or real_build(*a, **k))
    # Forgetting the held one first makes the count mean something in a process
    # where another test has already asked for a loopback request.
    monkeypatch.setattr(network, "_LOOPBACK_OPENER", None)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        for _ in range(8):
            with network.urlopen(url, timeout=5) as response:
                assert response.read() == b"ok"
    finally:
        server.shutdown()
        server.server_close()

    assert built["n"] == 1, f"the loopback transport was built {built['n']} times"


def test_a_dead_address_is_a_miss_and_not_a_deadline():
    """The plane decision's worst case is a port with nothing behind it, and a
    port with nothing behind it is answered by the connect, not the HTTP read."""
    from app.providers import local_discovery

    assert hasattr(local_discovery, "_listening")
    assert local_discovery.CONNECT_TIMEOUT < local_discovery.PROBE_TIMEOUT, (
        "the liveness deadline must be the shorter of the two")
