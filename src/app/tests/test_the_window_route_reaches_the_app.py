"""The engine can ask the window to hide or quit, and the app does it.

B152, kept for the native app. The reader's words: *"when we close the app, it
shows a warning screen which is fine but we need dont show me again button and
more stylised warning box; and please no OS warning sound."* The GPUI app has
no webview and no page to draw that notice, so the property that remains is the
route: `/api/window` records the choice and prints a `KRIKO_WINDOW` line, the
same pipe `KRIKO_FOCUS` uses, and the Rust side turns the line into a hide or a
quit. Closing the window itself is `test_the_shell_runs_in_the_tray.py`.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.routers import focus
from app.web.settings import Settings

REPO = Path(__file__).resolve().parents[3]
ENGINE_RS = REPO / "kriko-gpui" / "src" / "engine.rs"
APP_RS = REPO / "kriko-gpui" / "src" / "app.rs"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
        shell_attached=True,
    ))
    with TestClient(app) as c:
        yield c


def test_the_notice_shows_until_the_reader_says_not_to(client, capfd):
    assert client.get("/api/window").json() == {"shell": True, "close_notice": True}
    client.post("/api/window", json={"action": "hide", "remember": True})
    assert f"{focus.WINDOW_LINE} hide" in capfd.readouterr().out
    assert client.get("/api/window").json()["close_notice"] is False


def test_settings_can_bring_it_back_and_turn_it_off_without_closing(client, capfd):
    client.post("/api/window", json={"action": "hide", "remember": True})
    capfd.readouterr()
    client.put("/api/window/close-notice", json={"on": True})
    assert client.get("/api/window").json()["close_notice"] is True
    client.put("/api/window/close-notice", json={"on": False})
    assert client.get("/api/window").json()["close_notice"] is False
    assert focus.WINDOW_LINE not in capfd.readouterr().out


def test_quit_and_ack_reach_the_shell_and_remember_nothing(client, capfd):
    client.post("/api/window", json={"action": "ack"})
    client.post("/api/window", json={"action": "quit", "remember": False})
    out = capfd.readouterr().out
    assert f"{focus.WINDOW_LINE} ack" in out and f"{focus.WINDOW_LINE} quit" in out
    assert client.get("/api/window").json()["close_notice"] is True


def test_an_action_the_shell_does_not_know_is_refused(client, capfd):
    assert client.post("/api/window", json={"action": "exec calc"}).status_code == 422
    assert focus.WINDOW_LINE not in capfd.readouterr().out


def test_the_shell_and_the_engine_agree_on_the_line():
    engine = ENGINE_RS.read_text(encoding="utf-8")
    assert f'const WINDOW_LINE: &str = "{focus.WINDOW_LINE}";' in engine
    assert "line.contains(WINDOW_LINE)" in engine
    for action, event in (("hide", "Hide"), ("quit", "Quit")):
        assert f'"{action}" => Some(ShellEvent::{event})' in engine


def test_the_app_acts_on_what_the_engine_asked():
    """Hide hides the window; quit stops the engine and ends the app."""
    app = APP_RS.read_text(encoding="utf-8")
    assert re.search(r"ShellEvent::Hide\s*=>\s*shell::hide_window\(\)", app)
    assert re.search(r"ShellEvent::Quit\s*=>\s*Self::quit\(cx\)", app)


def test_the_window_line_cannot_be_mistaken_for_another():
    from app.sidecar import PORT_LINE

    assert PORT_LINE not in focus.WINDOW_LINE and focus.FOCUS_LINE not in focus.WINDOW_LINE
