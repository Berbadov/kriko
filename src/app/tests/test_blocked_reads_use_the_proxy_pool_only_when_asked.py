"""Rotating proxies for pages that block reads: off by default, rotation only where blocking was measured (#271).

The reader's words: "rotating proxies for aversion." (read as *evasion*; the
issue asked to be corrected if that was wrong.)

The policy, as the issue set it, is what is held here rather than the
plumbing:

* the pool is **off unless switched on**, and then still touches only a host
  whose direct read was measured as refused;
* a proxy that fails is **retired**, and with none left the read is **direct**,
  with the log saying so;
* a page still blocked after `MAX_TRIES` proxies is **"could not be read"**, not
  retried; `robots.txt` is honoured before any proxied attempt;
* the log says which reads used a proxy and **never the login**.

Everything runs on loopback sockets: a "site" that answers 403 to a direct read
and a stand-in HTTP proxy that gets through (or does not, by mode).
"""

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import chatweb, keys
from app.providers import fetch, proxypool
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings

LOGIN = "rotator:hunter2-do-not-leak"
PAGE = "<html><body><p>Owners report the gearbox whines above 3000 rpm.</p></body></html>"


class _Servers:
    def __init__(self):
        self.site_hits: list[str] = []
        self.proxy_hits: list[dict] = []
        self.proxy_mode = {"answer": 200}
        self.robots = ""
        self.direct = {"/page": 403, "/ok": 200, "/private": 403}


@pytest.fixture
def world(monkeypatch, tmp_path):
    servers = _Servers()

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            servers.site_hits.append(self.path)
            if self.path == "/robots.txt":
                body, code = servers.robots.encode(), 200 if servers.robots else 404
            else:
                code = servers.direct.get(self.path, 404)
                body = PAGE.encode() if code == 200 else b"Forbidden"
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            servers.proxy_hits.append({"target": self.path,
                                       "auth": self.headers.get("Proxy-Authorization", ""),
                                       "port": self.server.server_address[1]})
            code = servers.proxy_mode["answer"]
            body = PAGE.encode() if code == 200 else b"nope"
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    def serve(handler):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        return httpd

    site, proxy_a, proxy_b = serve(Site), serve(Proxy), serve(Proxy)
    servers.site = f"http://127.0.0.1:{site.server_address[1]}"
    servers.proxy_a = f"http://127.0.0.1:{proxy_a.server_address[1]}"
    servers.proxy_b = f"http://127.0.0.1:{proxy_b.server_address[1]}"
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setattr(chatweb, "_public_url", lambda url: url)  # these hosts are loopback stand-ins
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    monkeypatch.setenv("KRIKO_PROXY_AUTH", LOGIN)
    proxypool.forget()
    yield servers
    proxypool.remember_path(None)
    for httpd in (site, proxy_a, proxy_b):
        httpd.shutdown()
        httpd.server_close()


def _dead_address():
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{one.getsockname()[1]}"


def _read(world, router, path="/page", lines=None):
    sink = (lines.append if lines is not None else None)
    reader = chatweb.reader(timeout=3.0, proxies=router.view(sink) if router else None)
    return reader(world.site + path)


def test_with_no_pool_a_refused_read_is_just_unreadable_and_no_proxy_is_touched(world):
    assert _read(world, None).text == ""
    assert world.proxy_hits == []


def test_the_pool_is_off_unless_switched_on_even_with_addresses_saved(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        state.put_settings(conn, {proxypool.SETTING_POOL: "http://127.0.0.1:9999"})
    finally:
        conn.close()
    proxypool.remember_path(path)
    try:
        assert proxypool.shared() is None
        assert proxypool.reader_options() == {}
    finally:
        proxypool.remember_path(None)


def test_a_refused_host_is_read_through_the_pool_and_the_log_names_no_login(world):
    router = proxypool.Router([world.proxy_a, world.proxy_b], LOGIN)
    lines: list[str] = []
    page = _read(world, router, lines=lines)
    assert "gearbox whines" in page.text
    assert [hit["target"] for hit in world.proxy_hits] == [world.site + "/page"]
    assert world.proxy_hits[0]["auth"].startswith("Basic "), "the login reaches the proxy"
    text = "\n".join(lines)
    assert "refused a direct read" in text and "read through proxy 1 of 2" in text
    assert "hunter2" not in text and LOGIN not in text and "rotator" not in text


def test_a_host_that_never_blocked_is_never_sent_through_a_proxy(world):
    router = proxypool.Router([world.proxy_a], LOGIN)
    assert "gearbox" in _read(world, router, "/ok").text
    assert world.proxy_hits == []
    assert not router.should_route("127.0.0.1")


def test_once_measured_as_blocked_later_reads_go_straight_to_the_pool(world):
    router = proxypool.Router([world.proxy_a], LOGIN)
    _read(world, router)
    direct_before = len(world.site_hits)
    _read(world, router)
    assert [hit for hit in world.site_hits[direct_before:] if hit == "/page"] == []
    assert len(world.proxy_hits) == 2


def test_requests_rotate_across_the_pool(world):
    router = proxypool.Router([world.proxy_a, world.proxy_b], LOGIN)
    for _ in range(4):
        _read(world, router)
    ports = [hit["port"] for hit in world.proxy_hits]
    assert len(set(ports)) == 2 and ports[0] != ports[1]


def test_a_dead_proxy_is_retired_and_the_next_one_answers(world):
    router = proxypool.Router([_dead_address(), world.proxy_a], LOGIN)
    lines: list[str] = []
    assert "gearbox" in _read(world, router, lines=lines).text
    assert any("proxy 1 of 2" in line and "failed" in line and "not used for 300 s" in line for line in lines)
    assert [proxy.index for proxy in router.healthy()] == [1]
    assert all("hunter2" not in line for line in lines)


def test_a_retired_proxy_is_tried_again_after_its_time(world):
    now = [0.0]
    router = proxypool.Router([world.proxy_a, world.proxy_b], "", clock=lambda: now[0])
    router.retire(router.proxies[0], "x")
    assert [proxy.index for proxy in router.healthy()] == [1]
    now[0] = proxypool.RETIRE_SECONDS + 1
    assert [proxy.index for proxy in router.healthy()] == [0, 1]


def test_with_every_proxy_retired_the_read_is_direct_and_says_so(world):
    router = proxypool.Router([world.proxy_a], LOGIN)
    router.retire(router.proxies[0], "x")
    lines: list[str] = []
    assert _read(world, router, lines=lines).text == ""
    assert any("no healthy proxy is left; reading directly" in line for line in lines)
    assert world.proxy_hits == []
    assert router.snapshot()["direct_fallbacks"] == 1


def test_a_block_that_persists_after_rotation_is_reported_and_not_retried(world):
    world.proxy_mode["answer"] = 403
    router = proxypool.Router([world.proxy_a, world.proxy_b, world.proxy_a + "/", ], LOGIN)
    lines: list[str] = []
    assert _read(world, router, lines=lines).text == ""
    assert len(world.proxy_hits) <= proxypool.MAX_TRIES
    assert any("could not be read" in line and "still blocked" in line for line in lines)
    assert router.snapshot()["unreadable"] == 1


def test_robots_txt_is_honoured_before_any_proxied_attempt(world):
    world.robots = "User-agent: *\nDisallow: /private\n"
    router = proxypool.Router([world.proxy_a], LOGIN)
    lines: list[str] = []
    assert _read(world, router, "/private", lines=lines).text == ""
    assert world.proxy_hits == []
    assert any("robots.txt asks not to be read" in line for line in lines)


def test_a_proxy_that_wants_a_login_is_retired_not_mistaken_for_the_site(world):
    world.proxy_mode["answer"] = 407
    router = proxypool.Router([world.proxy_a, world.proxy_b], "")
    _read(world, router)
    assert router.snapshot()["retirements"] >= 1


def _switch_on(tmp_path, *addresses):
    """Turn the pool on the way the reader does: through the saved settings."""
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        state.put_settings(conn, {proxypool.SETTING_ENABLED: "1",
                                  proxypool.SETTING_POOL: "\n".join(addresses)})
    finally:
        conn.close()
    proxypool.remember_path(path)
    return proxypool.shared()


@pytest.mark.parametrize("new_login", ["new-user:new-password", ""])
def test_cached_pool_uses_the_current_proxy_login(world, tmp_path, monkeypatch, new_login):
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    try:
        state.put_settings(conn, {proxypool.SETTING_ENABLED: "1",
                                  proxypool.SETTING_POOL: world.proxy_a})
    finally:
        conn.close()
    monkeypatch.setenv("KRIKO_PROXY_AUTH", "old-user:old-password")
    proxypool.remember_path(path)
    try:
        first = proxypool.shared()
        assert first is not None
        assert "gearbox whines" in _read(world, first).text
        assert world.proxy_hits[-1]["auth"] == "Basic " + base64.b64encode(
            b"old-user:old-password").decode()

        if new_login:
            monkeypatch.setenv("KRIKO_PROXY_AUTH", new_login)
        else:
            monkeypatch.delenv("KRIKO_PROXY_AUTH")
        # Force the settings refresh while keeping the app-state path and
        # proxy addresses unchanged, as happens after the normal cache TTL.
        monkeypatch.setattr(proxypool, "SETTINGS_TTL", -1)
        refreshed = proxypool.shared()

        assert refreshed is not None
        assert "gearbox whines" in _read(world, refreshed).text
        expected = "Basic " + base64.b64encode(new_login.encode()).decode() if new_login else ""
        assert world.proxy_hits[-1]["auth"] == expected
    finally:
        proxypool.remember_path(None)


def test_the_page_fetcher_uses_the_pool_the_same_way(world, tmp_path):
    router = _switch_on(tmp_path, world.proxy_a)
    assert router is not None
    text = fetch.reader(timeout=3.0)(world.site + "/page", allow_private=True,
                                     allow_fallback=False).text
    assert "gearbox whines" in text
    assert len(world.proxy_hits) == 1 and router.should_route("127.0.0.1")
    assert world.proxy_hits[0]["auth"].startswith("Basic ")


def test_the_page_fetcher_reports_a_persistent_block_and_stops(world, tmp_path):
    world.proxy_mode["answer"] = 429
    router = _switch_on(tmp_path, world.proxy_a, world.proxy_b)
    assert router is not None
    assert fetch.reader(timeout=3.0)(world.site + "/page", allow_private=True,
                                     allow_fallback=False).text == ""
    assert len(world.proxy_hits) == 2 and router.snapshot()["unreadable"] == 1


def test_the_pool_never_sees_a_page_the_reader_did_not_ask_to_read(world, monkeypatch):
    """Rotation does not make a loopback or private address reachable."""
    router = proxypool.Router([world.proxy_a], LOGIN)
    monkeypatch.undo()  # back to the real address check
    assert chatweb.reader(timeout=1.0, proxies=router)("http://127.0.0.1:1/x").text == ""
    assert world.proxy_hits == []


# ── Settings ─────────────────────────────────────────────────────────────

def _client(tmp_path):
    return TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl")))


def test_settings_ship_the_pool_off_and_say_so(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    monkeypatch.delenv("KRIKO_PROXY_AUTH", raising=False)
    body = _client(tmp_path).get("/api/proxies").json()
    assert body["enabled"] is False and body["active"] is False and body["pool"] == []
    assert body["login_saved"] is False and body["learned"] is None


def test_the_switch_and_the_pool_are_validated_and_saved_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    client = _client(tmp_path)
    assert client.put("/api/prefs", json={"proxy_pool": "http://user:pw@host:8080"}).status_code == 422
    assert client.put("/api/prefs", json={"proxy_pool": "socks5://host:1080"}).status_code == 422
    assert client.put("/api/prefs", json={"proxy_pool": "host:8080"}).status_code == 422
    assert client.put("/api/prefs", json={"proxy_enabled": "maybe"}).status_code == 422
    saved = client.put("/api/prefs", json={
        "proxy_enabled": "1",
        "proxy_pool": "http://p1.example:8080, http://p2.example:8080\nhttp://p1.example:8080"})
    assert saved.status_code == 200
    body = client.get("/api/proxies").json()
    assert body["enabled"] and body["active"]
    assert body["pool"] == ["http://p1.example:8080", "http://p2.example:8080"]


def test_the_login_lives_in_the_key_store_and_is_never_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    monkeypatch.delenv("KRIKO_PROXY_AUTH", raising=False)
    client = _client(tmp_path)
    client.put("/api/keys", json={"values": {"proxy": LOGIN}})
    everything = json.dumps([client.get("/api/keys").json(), client.get("/api/proxies").json(),
                             client.get("/api/prefs").json()])
    assert LOGIN not in everything and "hunter2" not in everything
    assert client.get("/api/proxies").json()["login_saved"] is True
    monkeypatch.delenv("KRIKO_PROXY_AUTH", raising=False)


def test_check_asks_each_saved_proxy_for_one_page(tmp_path, monkeypatch, world):
    monkeypatch.setattr(keys, "env_path", lambda home=None: tmp_path / "env")
    client = _client(tmp_path)
    client.put("/api/prefs", json={"proxy_pool": f"{world.proxy_a}\n{_dead_address()}"})
    monkeypatch.setattr(proxypool, "CHECK_TARGET", world.site + "/ok")
    shown = client.post("/api/proxies/check").json()
    assert [row["ok"] for row in shown["results"]] == [True, False]
    assert "could not connect" in shown["results"][1]["error"]
    assert LOGIN not in json.dumps(shown)
