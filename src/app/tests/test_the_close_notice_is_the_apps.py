"""B152: closing the window asks in Kriko's own box, once, silently.

The reader's words: *"when we close the app, it shows a warning screen which
is fine but we need dont show me again button and more stylised warning box;
and please no OS warning sound."* The native message box is gone from the
shell; the page draws the notice and answers through `/api/window`, which
prints a line the shell acts on — the same pipe `KRIKO_FOCUS` uses.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.routers import focus
from app.web.settings import Settings

REPO = Path(__file__).resolve().parents[3]
MAIN_RS = REPO / "tauri" / "src-tauri" / "src" / "main.rs"


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
    main_rs = MAIN_RS.read_text(encoding="utf-8")
    assert f'const WINDOW_LINE: &str = "{focus.WINDOW_LINE}";' in main_rs
    assert "if line.contains(WINDOW_LINE) {\n                        window_answer" in main_rs
    for action in ("hide", "quit"):
        assert f'"{action}" =>' in main_rs
    assert 'page.eval("window.__krikoClose && window.__krikoClose()")' in main_rs


def test_the_close_button_no_longer_opens_a_native_box():
    """A native message box is the sound the reader asked to be rid of."""
    main_rs = MAIN_RS.read_text(encoding="utf-8")
    close = main_rs.split("tauri::WindowEvent::CloseRequested", 1)[1].split("WindowEvent::Destroyed", 1)[0]
    assert "dialog" not in close and "ask_page_to_close(window)" in close
    assert "fn hint_still_running" not in main_rs


def test_the_window_line_cannot_be_mistaken_for_another():
    from app.sidecar import PORT_LINE

    assert PORT_LINE not in focus.WINDOW_LINE and focus.FOCUS_LINE not in focus.WINDOW_LINE
