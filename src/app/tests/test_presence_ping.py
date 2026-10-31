"""The optional anonymous presence ping.

Off by default, and the payload is exactly two facts: a random install id and
the app version. No question, no product, no page, no key — the tests read the
bytes that would cross the wire, so a future field has to be argued for here.
"""

import json
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app import presence
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


def _conn(tmp_path):
    return state.connect(Path(tmp_path) / "app.sqlite")


def _settings(tmp_path, **overrides):
    base = Path(tmp_path)
    return Settings(
        app_state_path=base / "app.sqlite",
        store_path=base / "store.sqlite",
        analysis_log_path=base / "analyses.jsonl",
        **overrides,
    )


def test_off_by_default_and_no_endpoint_means_nothing_is_sent(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(presence, "_open", lambda url, body, timeout: sent.append((url, body)))
    settings = _settings(tmp_path, presence_endpoint="https://presence.example.test/ping")
    assert presence.maybe_ping(settings, settings.app_state_path, "0.3.7") is False
    assert sent == []


def test_an_opted_in_install_sends_id_and_version_only_once_a_day(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(presence, "_open", lambda url, body, timeout: sent.append((url, body)))
    conn = _conn(tmp_path)
    state.put_settings(conn, {"presence_enabled": "1"})
    conn.close()
    settings = _settings(tmp_path, presence_endpoint="https://presence.example.test/ping")

    assert presence.maybe_ping(settings, settings.app_state_path, "0.3.7") is True
    assert presence.maybe_ping(settings, settings.app_state_path, "0.3.7") is False
    assert len(sent) == 1
    url, body = sent[0]
    assert url == "https://presence.example.test/ping"
    payload = json.loads(body)
    assert set(payload) == {"id", "version"}
    assert payload["version"] == "0.3.7"
    assert len(payload["id"]) == 32

    conn = _conn(tmp_path)
    assert state.all_settings(conn)["presence_last_day"] == date.today().isoformat()
    conn.close()


def test_the_install_id_is_stable_across_pings(tmp_path):
    conn = _conn(tmp_path)
    first = presence.install_id(conn)
    second = presence.install_id(conn)
    conn.close()
    assert first == second


def test_a_failed_ping_is_not_a_crash_and_is_retried_next_day(tmp_path, monkeypatch):
    def boom(url, body, timeout):
        raise OSError("offline")

    monkeypatch.setattr(presence, "_open", boom)
    conn = _conn(tmp_path)
    state.put_settings(conn, {"presence_enabled": "1"})
    conn.close()
    settings = _settings(tmp_path, presence_endpoint="https://presence.example.test/ping")
    assert presence.maybe_ping(settings, settings.app_state_path, "0.3.7") is False
    conn = _conn(tmp_path)
    assert state.all_settings(conn).get("presence_last_day", "") == ""
    conn.close()


def test_a_non_https_endpoint_is_refused(tmp_path):
    # The real `_open` is used: the scheme check raises before any network
    # call, and `maybe_ping` turns that into "not sent".
    conn = _conn(tmp_path)
    state.put_settings(conn, {"presence_enabled": "1"})
    conn.close()
    settings = _settings(tmp_path, presence_endpoint="http://insecure.example.test/ping")
    assert presence.maybe_ping(settings, settings.app_state_path, "0.3.7") is False


def test_the_status_endpoint_reports_the_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("KRIKO_NO_PRESENCE", "1")
    monkeypatch.setenv("KRIKO_NO_PACK_AUTOUPDATE", "1")
    settings = _settings(tmp_path, presence_endpoint="https://presence.example.test/ping")
    client = TestClient(create_app(settings))
    got = client.get("/api/presence").json()
    assert got == {"enabled": False, "endpoint": "https://presence.example.test/ping", "last_day": ""}
    conn = state.connect(settings.app_state_path)
    state.put_settings(conn, {"presence_enabled": "1"})
    conn.close()
    got = client.get("/api/presence").json()
    assert got["enabled"] is True


def test_the_ping_never_carries_a_key_or_a_question(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(presence, "_open", lambda url, body, timeout: sent.append(body))
    conn = _conn(tmp_path)
    state.put_settings(conn, {"presence_enabled": "1", "llm_key_openai": "sk-secret-value"})
    conn.close()
    settings = _settings(tmp_path, presence_endpoint="https://presence.example.test/ping")
    presence.maybe_ping(settings, settings.app_state_path, "0.3.7")
    assert len(sent) == 1
    assert b"sk-secret-value" not in sent[0]
