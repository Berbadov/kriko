"""Who the server answers, on a port a web page can reach.

The port is 127.0.0.1 and there are no accounts, and both of those were the
argument for having no authorisation. They hold against the *network*. They do
not hold against the browser: the sidecar also binds 8787, a constant written
down in this repository and hardcoded in the extension, and every page the
reader visits runs script that can reach it.

Two of these tests are the ones that matter, because they are the two things
`Origin` and `Host` catch that the other cannot:

* a cross-site GET, which executes even though the page cannot read the
  reply — and `GET /api/focus` is consume-once, so it does damage unread;
* DNS rebinding, where the attacker's own domain resolves to 127.0.0.1 and is
  therefore *same-origin* with this server. No `Origin` check can see it.

The rest hold the doors that must stay open: the extension, the desktop shell,
`curl`, and the shell's own hand-rolled HTTP/1.0 health poll.
"""

import pytest
from fastapi.testclient import TestClient

from app.web import origins
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


# ── what must be refused ─────────────────────────────────────────────────


def test_a_page_on_the_open_web_is_refused(client):
    """The whole point. `evil.example` cannot read the reply thanks to CORS,
    but a simple GET still *runs*, and one of ours is consume-once."""
    got = client.get(
        "/api/health", headers={"Origin": "https://evil.example"}
    )
    assert got.status_code == 403
    assert "evil.example" in got.json()["detail"]


def test_the_consume_once_nudge_cannot_be_burned_from_a_page(client):
    """Concretely: a page cannot spend a focus the reader was about to act
    on. This is the endpoint that made the check worth writing."""
    client.post("/api/focus", json={"route": "knowledge"})
    refused = client.get("/api/focus", headers={"Origin": "https://evil.example"})
    assert refused.status_code == 403
    # And the nudge is still there for the window that was meant to have it.
    assert client.get("/api/focus").json()["route"] == "knowledge"


def test_a_rebound_dns_name_is_refused_even_though_it_is_same_origin(client):
    """The attack `Origin` cannot see.

    `evil.example` pointed at 127.0.0.1 makes the attacker's page
    same-origin with this server: the browser sends their host, their origin,
    and is entirely satisfied. Only the `Host` header shows what happened.
    """
    got = client.get(
        "/api/health",
        headers={"Host": "evil.example", "Origin": "http://evil.example"},
    )
    assert got.status_code == 403

    # And on its own, without the origin that happens to also be refusable:
    # the rebinding case where the page arrives from the extension's own
    # origin, or from no origin at all.
    alone = client.get("/api/health", headers={"Host": "evil.example"})
    assert alone.status_code == 403
    assert "127.0.0.1" in alone.json()["detail"]
    assert origins.host_is_ours("evil.example") is False


def test_a_null_origin_is_refused():
    """A sandboxed iframe or a `file://` page — the one origin an attacker
    gets without owning a domain, and nothing legitimate arrives that way."""
    assert origins.origin_is_allowed("null") is False


def test_an_exotic_scheme_is_not_waved_through():
    assert origins.origin_is_allowed("gopher://localhost") is False
    assert origins.origin_is_allowed("javascript:void 0") is False


# ── what must keep working ───────────────────────────────────────────────


def test_the_extension_is_let_in(client):
    """Its id is unknowable in advance, so the scheme is what is matched."""
    got = client.get(
        "/api/health",
        headers={"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"},
    )
    assert got.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8787",
        "http://localhost:1420",
        "http://[::1]:8787",
        "moz-extension://deadbeef",
    ],
)
def test_the_app_talking_to_itself_is_let_in(origin):
    assert origins.origin_is_allowed(origin) is True


@pytest.mark.parametrize(
    "origin", ["tauri://localhost", "asset://localhost", "http://tauri.localhost"]
)
def test_the_retired_webview_shell_is_no_longer_trusted(origin):
    """The desktop app is native and sends no Origin; the webview shell it
    replaced is gone, so its schemes and host are strangers now."""
    assert origins.origin_is_allowed(origin) is False


def test_no_origin_is_not_an_attack(client):
    """`curl`, the test suite, a native client, and every same-origin GET.

    Refusing these would buy nothing: a caller that can set arbitrary headers
    is not the caller a header check stops.
    """
    assert client.get("/api/health").status_code == 200


def test_a_missing_host_is_the_shell_polling_health():
    """`wait_until_healthy` writes its own request over a raw TcpStream,
    because pulling in an HTTP client to poll one endpoint was the wrong
    trade — and HTTP/1.0 has no Host. Refusing it means the window never
    opens, which is a worse outcome than every attack on this list."""
    assert origins.host_is_ours(None) is True
    assert origins.host_is_ours("") is True


def test_a_bare_hostname_is_not_a_rebinding_target():
    """`testserver`, `localhost`, a LAN machine name: no dot, so no public
    DNS record, so nothing an attacker can point at this port. The rule has
    no test-only exemption on purpose — a rule with a hole cut in it for the
    suite is a rule the suite stops testing."""
    assert origins.host_is_ours("testserver") is True
    assert origins.host_is_ours("kriko-box:8787") is True
    assert origins.host_is_ours("127.0.0.1:8787") is True
    assert origins.host_is_ours("[::1]:8787") is True


def test_the_check_is_case_and_port_insensitive():
    assert origins.origin_is_allowed("HTTP://LocalHost:9999") is True
    assert origins.host_is_ours("LOCALHOST:8787") is True


def test_it_runs_before_anything_else_can_act_on_the_request(client):
    """Registered first and therefore outermost. A refused request must not
    record an extension sighting, open app.sqlite, or reach a router."""
    names = [m.kwargs["dispatch"].__name__ for m in client.app.user_middleware]
    assert names[0] == "only_from_here"
