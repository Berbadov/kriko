import json
import sys

import pytest

from app.web.app import create_app
from app.web.origins import terminal_origin_is_allowed
from app.web.settings import Settings


def _client(tmp_path):
    from fastapi.testclient import TestClient

    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
            )
        )
    )


def test_terminal_origin_allows_the_shell_and_loopback_only():
    assert terminal_origin_is_allowed(None)
    assert terminal_origin_is_allowed("tauri://localhost")
    assert terminal_origin_is_allowed("http://127.0.0.1:8787")
    assert not terminal_origin_is_allowed("chrome-extension://abc")
    assert not terminal_origin_is_allowed("moz-extension://abc")
    assert not terminal_origin_is_allowed("https://evil.example")
    assert not terminal_origin_is_allowed("null")


def test_the_socket_refuses_an_extension_origin(tmp_path):
    client = _client(tmp_path)
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/api/terminal/ws", headers={"origin": "chrome-extension://abc"}
        ):
            pass


def test_a_session_start_failure_is_reported_on_the_socket(tmp_path, monkeypatch):
    """B109: a crash in `SESSION.start()` must not be a bare disconnect.

    Before this, the reader's only way to learn *why* the terminal panel
    said "disconnected" was `app.log` — itself unreachable until the 0.7.6
    `log_config` fix. The handler now catches the failure, still logs it
    (`test_an_unhandled_exception_in_a_route_reaches_the_app_log` in
    `test_sidecar.py` covers that half end-to-end), and reports it as a
    frame on the socket the reader is already looking at.
    """
    from app.providers import termpty

    def _raise(*_a, **_k):
        raise OSError("no such shell")

    monkeypatch.setattr(termpty.SESSION, "start", _raise)

    client = _client(tmp_path)
    with client.websocket_connect(
        "/api/terminal/ws", headers={"origin": "tauri://localhost"}
    ) as ws:
        frame = json.loads(ws.receive_text())
        assert frame["type"] == "error"
        assert "no such shell" in frame["message"]


@pytest.mark.skipif(sys.platform == "win32", reason="posix pty only here")
def test_the_socket_runs_a_real_shell_round_trip(tmp_path):
    from app.providers.termpty import SESSION

    client = _client(tmp_path)
    try:
        with client.websocket_connect(
            "/api/terminal/ws", headers={"origin": "tauri://localhost"}
        ) as ws:
            ws.send_text(json.dumps({"type": "data", "data": "echo kriko-term-ok\n"}))
            seen = ""
            for _ in range(200):
                msg = json.loads(ws.receive_text())
                seen += msg["data"]
                if "kriko-term-ok" in seen:
                    break
            assert "kriko-term-ok" in seen
    finally:
        SESSION.close()
