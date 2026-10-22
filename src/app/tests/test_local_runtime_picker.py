"""Settings picks the program the local agent talks to, and checks it answers (#267).

The reader's words: "local agent inference software selection". Done when a
picker names the runtimes (Ollama, llama.cpp server, vLLM, LM Studio, any
OpenAI-compatible endpoint), takes an address, and a check says whether it
answers and which models it lists. The check is exercised here against a real
socket speaking the protocol, because the check *is* a socket question.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.providers import local_discovery, local_runtimes
from app.providers.local_discovery import discover as real_discover
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def server():
    """An OpenAI-compatible server; `ollama` turns on the `/api/version` answer."""
    mode = {"ollama": False, "models": ["qwen3:8b", "gemma4:e2b"]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/v1/models":
                body = {"data": [{"id": name} for name in mode["models"]]}
            elif self.path == "/api/version" and mode["ollama"]:
                body = {"version": "0.12.0"}
            else:
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    local_discovery.forget_discovery()
    yield type("Server", (), {"url": f"http://127.0.0.1:{httpd.server_address[1]}", "mode": mode})
    httpd.shutdown()
    httpd.server_close()


def _client(tmp_path):
    return TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl")))


def _dead_url():
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{one.getsockname()[1]}"


def test_the_picker_lists_what_discovery_already_looks_for_and_a_typed_in_endpoint(tmp_path):
    body = _client(tmp_path).get("/api/local-runtimes").json()
    rows = {row["id"]: row for row in body["runtimes"]}
    assert list(rows) == ["ollama", "lm-studio", "llama-server", "vllm", "custom"]
    assert rows["llama-server"]["name"] == "llama.cpp server"
    assert rows["ollama"]["url"] == "http://127.0.0.1:11434"
    assert rows["vllm"]["url"] == f"http://{'127.0.0.1'}:8000"
    assert rows["custom"]["url"] == ""
    assert body["chosen"] == "" and body["url"] == ""


def test_a_server_that_answers_lists_its_models(tmp_path, server):
    local_discovery.forget_discovery()
    shown = _client(tmp_path).post("/api/local-runtimes/check",
                                   json={"runtime": "custom", "url": server.url}).json()
    assert shown["up"] and shown["models"] == ["qwen3:8b", "gemma4:e2b"]
    assert shown["detected"] == "OpenAI-compatible server"
    assert "lists 2 models" in shown["message"]
    assert shown["loader"]["supported"] is False and shown["loader"]["help"]


def test_ollama_is_recognised_by_its_own_version_answer(tmp_path, server):
    server.mode["ollama"] = True
    shown = _client(tmp_path).post("/api/local-runtimes/check",
                                   json={"runtime": "ollama", "url": server.url}).json()
    assert shown["detected"] == "Ollama" and shown["loader"]["supported"] is True


def test_picking_ollama_against_another_server_says_it_will_be_treated_as_generic(tmp_path, server):
    shown = _client(tmp_path).post("/api/local-runtimes/check",
                                   json={"runtime": "ollama", "url": server.url}).json()
    assert shown["up"] and "does not answer like Ollama" in shown["message"]


def test_a_silent_address_says_what_to_start_and_installs_nothing(tmp_path):
    shown = _client(tmp_path).post("/api/local-runtimes/check",
                                   json={"runtime": "lm-studio", "url": _dead_url()}).json()
    assert shown["up"] is False and shown["models"] == []
    assert "Nothing answers" in shown["message"] and "Developer tab" in shown["message"]


def test_a_server_with_no_models_says_to_download_one(tmp_path, server):
    server.mode["models"] = []
    shown = _client(tmp_path).post("/api/local-runtimes/check",
                                   json={"runtime": "custom", "url": server.url}).json()
    assert shown["up"] and "lists no models" in shown["message"]


def test_a_bad_address_is_refused_by_the_check_and_by_the_save(tmp_path):
    client = _client(tmp_path)
    shown = client.post("/api/local-runtimes/check", json={"runtime": "custom", "url": "file:///etc/passwd"}).json()
    assert shown["up"] is False and "address" in shown["message"]
    assert client.put("/api/prefs", json={"local_url": "http://user:pw@127.0.0.1:1234"}).status_code == 422
    assert client.put("/api/prefs", json={"local_url": "ftp://127.0.0.1"}).status_code == 422
    assert client.put("/api/prefs", json={"local_runtime": "mystery"}).status_code == 422


def test_the_choice_is_saved_with_the_other_settings_and_cleaned(tmp_path):
    client = _client(tmp_path)
    saved = client.put("/api/prefs", json={"local_runtime": "lm-studio",
                                          "local_url": "http://127.0.0.1:1234/v1/"}).json()
    assert saved["chosen"]["local_runtime"] == "lm-studio"
    assert saved["chosen"]["local_url"] == "http://127.0.0.1:1234"
    again = client.get("/api/local-runtimes").json()
    assert (again["chosen"], again["url"]) == ("lm-studio", "http://127.0.0.1:1234")
    cleared = client.put("/api/prefs", json={"local_runtime": "", "local_url": ""}).json()
    assert cleared["chosen"]["local_runtime"] == "" and cleared["chosen"]["local_url"] == ""


def test_a_chosen_address_is_the_one_the_local_plane_asks_first(tmp_path, server, monkeypatch):
    from app import localplane

    monkeypatch.setattr(local_discovery, "discover", real_discover)

    client = _client(tmp_path)
    client.put("/api/prefs", json={"local_runtime": "custom", "local_url": server.url})
    plan = localplane.resolve(tmp_path / "app.sqlite", with_search=False)
    assert plan["url"] == server.url and plan["models"] == ["qwen3:8b", "gemma4:e2b"]
    assert local_runtimes.default_url("vllm").endswith(":8000")
