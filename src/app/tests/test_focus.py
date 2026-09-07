"""Raising the desktop window from outside it.

The extension's "Open in Kriko" used to be a link, which opened the report in
a *browser tab* next to the app the reader already had running. The handoff is
now a posted route: the engine records it and prints a line the shell is
already listening for. These tests hold the three joints of that — the
validation, the consume-once, and the two constants on either side of a pipe
with no compiler to check them against each other.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.routers import focus
from app.web.settings import Settings

REPO = Path(__file__).resolve().parents[3]


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


def test_nothing_pending_is_not_an_error(client):
    """The window polls this forever. A 404 every two seconds is not a design."""
    assert client.get("/api/focus").json() == {"route": None}


def test_a_posted_route_is_handed_to_the_window_exactly_once(client):
    """A nudge acted on is spent.

    Two windows would otherwise both jump, and a window opened by hand later
    would replay a navigation nobody asked for a second time.
    """
    posted = client.post("/api/focus", json={"route": "#/result/abc123"})
    assert posted.json()["route"] == "result/abc123"
    assert client.get("/api/focus").json() == {"route": "result/abc123"}
    assert client.get("/api/focus").json() == {"route": None}


def test_the_leading_hash_is_the_extension_speaking_the_ui_dialect(client):
    """`#/result/x` is what the SPA's own links look like, so it is accepted
    and normalised rather than refused on a technicality."""
    for given in ("#/result/x", "/result/x", "result/x"):
        client.post("/api/focus", json={"route": given})
        assert client.get("/api/focus").json()["route"] == "result/x"


@pytest.mark.parametrize(
    "route",
    [
        "javascript:alert(1)",
        "result/../../etc/passwd",
        "https://evil.invalid/",
        "result/x?q=1",
        "result/x#/other",
        "Result/X",
        "a" * 200,
    ],
)
def test_a_route_that_is_not_a_route_is_refused(client, route):
    """This arrives from the one client that cannot be authenticated, and it
    ends up in the SPA's `location.hash`. The shape is the whole defence."""
    assert client.post("/api/focus", json={"route": route}).status_code == 422


def test_a_stale_nudge_is_dropped_rather_than_replayed(client, monkeypatch):
    """A window opened minutes later must not jump to a forgotten report."""
    client.post("/api/focus", json={"route": "result/abc"})
    # Relative to the clock the POST actually read, not to zero: `monotonic`
    # counts from an arbitrary origin, so an absolute value here would happen
    # to be in the *past* on a machine that has been up for a while.
    stamped = client.app.state.focus["at"]
    monkeypatch.setattr(
        focus.time, "monotonic", lambda: stamped + focus.TTL_SECONDS + 1
    )
    assert client.get("/api/focus").json()["route"] is None


def test_the_shell_and_the_engine_agree_on_the_stdout_line():
    """Two constants, one pipe, no compiler between them.

    A rename on either side would silently stop raising the window: the POST
    still succeeds, the SPA still navigates, and the app just never comes to
    the front — which reads as the same dead button this replaced.
    """
    main_rs = (REPO / "tauri" / "src-tauri" / "src" / "main.rs").read_text()
    assert f'const FOCUS_LINE: &str = "{focus.FOCUS_LINE}";' in main_rs
    # And it must actually be acted on, not merely declared.
    assert "if line.contains(FOCUS_LINE) {\n                        show_window" in main_rs


def test_the_focus_line_cannot_be_mistaken_for_the_port_handshake():
    """The shell takes the first stdout line containing `PORT_LINE` as the
    port. A focus line that contained it would be parsed as a port and the
    handshake would be lost."""
    from app.sidecar import PORT_LINE

    assert PORT_LINE not in focus.FOCUS_LINE


def test_the_line_is_flushed_because_a_frozen_binary_buffers_stdout():
    """PyInstaller's stdout is a pipe, so it block-buffers. Without the flush
    the shell would receive the nudge when the process exited."""
    source = Path(focus.__file__).read_text(encoding="utf-8")
    assert 'print(f"{FOCUS_LINE} {route}", flush=True)' in source
