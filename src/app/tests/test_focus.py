"""Raising the desktop window from outside it.

The extension's "Open in Kriko" used to be a link, which opened the report in
a *browser tab* next to the app the reader already had running. The handoff is
now a posted route: the engine records it and prints a line the shell is
already listening for. These tests hold the three joints of that — the
validation, the consume-once, and the two constants on either side of a pipe
with no compiler to check them against each other.
"""

import re
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


@pytest.mark.parametrize(
    "route", ["result/abc123", "questions/abc123", "compare/abc123", "jobs"]
)
def test_every_route_the_panel_can_hand_over_fits_the_shape(client, route):
    """The closed shape is the defence, so it also decides what the extension
    is *able* to offer — and that constraint runs the other way too.

    The panel's "Ask the seller" and "Compare" buttons exist because those two
    app screens accept an id as a path segment. If either ever moved to a
    query-string-only address, this endpoint would refuse the handoff and the
    buttons would silently stop working; failing here instead is the point.
    """
    assert client.post("/api/focus", json={"route": route}).status_code == 200
    assert client.get("/api/focus").json()["route"] == route


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
    still succeeds, the app still has its route, and the window just never
    comes to the front, which reads as the same dead button this replaced.
    """
    engine = (REPO / "kriko-gpui" / "src" / "engine.rs").read_text(encoding="utf-8")
    assert f'const FOCUS_LINE: &str = "{focus.FOCUS_LINE}";' in engine
    # And it must actually be acted on, not merely declared: the line becomes
    # an event, and the window raises on it.
    assert "line.contains(FOCUS_LINE)" in engine and "ShellEvent::Focus" in engine
    app = (REPO / "kriko-gpui" / "src" / "app.rs").read_text(encoding="utf-8")
    assert re.search(r"ShellEvent::Focus\(\w+\)\s*=>\s*shell::show_window\(cx\)", app), (
        "the app receives the focus event and does not raise the window"
    )


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


# ── the honest answer about delivery ─────────────────────────────────────
#
# The old response said `raised: true` unconditionally, which is a claim this
# process is not in a position to make: it cannot see a window, and the line
# it prints goes into a pipe that may have nobody on the other end. That is
# how "Open in Kriko" came to look like a dead button — the extension was told
# the window had been raised, so it correctly declined to open a tab, and a
# reader running the sidecar by hand got nothing at all.


def test_unsupervised_says_so_rather_than_claiming_a_window(client):
    """No shell attached, so no window was raised, and the extension needs to
    hear that — a tab is the right answer here, not a silent nothing."""
    body = client.post("/api/focus", json={"route": "knowledge"}).json()
    assert body["delivery"] == "no_shell"
    assert body["raised"] is False
    # Still recorded: a window opened within the TTL should take the nudge.
    assert client.get("/api/focus").json()["route"] == "knowledge"


def test_supervised_claims_the_raise(tmp_path):
    """With a shell reading stdout, the printed line *is* the raise."""
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
            shell_attached=True,
        )
    )
    with TestClient(app) as client:
        body = client.post("/api/focus", json={"route": "knowledge"}).json()
    assert body["delivery"] == "raised"
    assert body["raised"] is True


def test_the_line_is_printed_even_with_no_shell(client, capfd):
    """Not a branch. If the print were conditional, the only path anyone ever
    exercises locally would be the one that does nothing."""
    client.post("/api/focus", json={"route": "packs"})
    assert f"{focus.FOCUS_LINE} packs" in capfd.readouterr().out


def test_the_shell_declares_its_supervision_when_it_spawns_the_sidecar():
    """The one fact the sidecar cannot work out for itself.

    A supervised sidecar and a hand-run one are identical over HTTP. If this
    flag goes missing from the spawn, every focus request reports `no_shell`
    and the extension opens a browser tab beside the running app, which is
    exactly the bug this whole path exists to fix, and nothing else would fail.
    """
    engine = (REPO / "kriko-gpui" / "src" / "engine.rs").read_text(encoding="utf-8")
    assert '.args(["--exit-with-parent", "--supervised"])' in engine


def test_the_sidecar_accepts_the_flag_the_shell_passes(capfd):
    """The other half of the same joint.

    A flag Rust passes and argparse has never heard of is not a degraded
    feature — argparse exits 2, so the sidecar never binds and the window
    never opens. Asked of the real parser rather than a copy of it, via the
    one argv that makes `main` describe itself and stop.
    """
    from app import sidecar

    with pytest.raises(SystemExit) as exited:
        sidecar.main(["--help"])
    assert exited.value.code == 0
    assert "--supervised" in capfd.readouterr().out


def test_settings_reads_the_supervision_flag_from_the_environment(monkeypatch):
    """The sidecar exports it; Settings.from_env picks it up. Through the
    environment because `Settings` is built after the flag is known and this
    is a fact about the process, not a configuration choice."""
    monkeypatch.setenv("KRIKO_SUPERVISED", "1")
    assert Settings.from_env().shell_attached is True
    monkeypatch.setenv("KRIKO_SUPERVISED", "0")
    assert Settings.from_env().shell_attached is False
    monkeypatch.delenv("KRIKO_SUPERVISED")
    assert Settings.from_env().shell_attached is False


# ── /api/health carries the two facts a broken door needs ────────────────
#
# Both of these are invisible from inside the window, which is why they had
# to be published: the reader whose "Open in Kriko" does nothing has no way
# to tell a lost 8787 from an unsupervised sidecar from a missing extension,
# and neither did we when they asked.


def test_health_publishes_the_extension_door_and_the_shell(client):
    body = client.get("/api/health").json()
    from app.web.settings import EXTENSION_PORT

    assert body["extension_port"] == EXTENSION_PORT
    assert "port_is_ours" in body
    assert body["shell_attached"] is False


def test_health_reports_a_shell_when_there_is_one(tmp_path):
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
            shell_attached=True,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/health").json()["shell_attached"] is True
