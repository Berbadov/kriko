"""The Local AI "Try it" box: one bounded question, and plain words when it cannot.

A fake chat server stands in for the model server (a real socket, because the
call is a socket question). What is pinned: the answer carries its speed from the
server's own token count and none when the server gave none; a prompt over the
limit and an empty one are refused before anything is sent; no server, no model,
and a model the server does not hold are a 409 that says what to do; a server that
is slow, down, or refuses is a gateway error in words; and the request that goes
out is capped.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import localtry
from app.providers import local_discovery
from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def chat():
    """A model server: `mode` shapes its next answer, `seen` keeps what it was sent."""
    mode = {"status": 200, "delay": 0.0, "usage": True, "text": "Hello from the model.", "models": ["qwen3:8b"]}
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            seen.append({"path": self.path, "body": json.loads(self.rfile.read(length))})
            time.sleep(mode["delay"])
            if mode["status"] != 200:
                payload = json.dumps({"error": {"message": "boom"}}).encode()
                self.send_response(mode["status"])
            else:
                body = {"choices": [{"message": {"content": mode["text"]}, "finish_reason": "stop"}]}
                if mode["usage"]:
                    body["usage"] = {"prompt_tokens": 9, "completion_tokens": 24, "total_tokens": 33}
                payload = json.dumps(body).encode()
                self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except OSError:
                pass

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield type("Chat", (), {"url": url, "mode": mode, "seen": seen})
    httpd.shutdown()
    httpd.server_close()


def _serve(monkeypatch, url: str, models: list[str]):
    """Discovery finds one server at `url`, holding `models`."""
    monkeypatch.setattr(
        local_discovery, "discover",
        lambda configured="", timeout=1.0: [{"name": "llama-server", "url": url, "up": True, "models": models}])


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(
            store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "analyses.jsonl"))) as one:
        yield one


def test_a_try_answers_with_its_speed_from_the_servers_own_count(chat, client, monkeypatch):
    _serve(monkeypatch, chat.url, ["qwen3:8b"])
    answer = client.post("/api/local-models/try", json={"prompt": "Say hello"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["ok"] is True and body["text"] == "Hello from the model."
    assert body["model"] == "qwen3:8b"
    assert body["output_tokens"] == 24
    assert body["tokens_per_second"] > 0, "a counted reply has a speed"
    sent = chat.seen[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["max_tokens"] == localtry.MAX_OUTPUT_TOKENS == 200
    assert sent["body"]["messages"] == [{"role": "user", "content": "Say hello"}]


def test_a_server_that_counts_no_tokens_gets_no_invented_speed(chat, client, monkeypatch):
    chat.mode["usage"] = False
    _serve(monkeypatch, chat.url, ["qwen3:8b"])
    body = client.post("/api/local-models/try", json={"prompt": "hi"}).json()
    assert body["ok"] and body["output_tokens"] is None and body["tokens_per_second"] is None


def test_the_reader_can_name_a_model_the_server_holds(chat, client, monkeypatch):
    _serve(monkeypatch, chat.url, ["qwen3:8b", "gemma4:e2b"])
    body = client.post("/api/local-models/try", json={"prompt": "hi", "model": "gemma4:e2b"}).json()
    assert body["model"] == "gemma4:e2b"
    assert chat.seen[0]["body"]["model"] == "gemma4:e2b"


def test_a_prompt_over_the_limit_or_empty_is_refused_before_anything_is_sent(chat, client, monkeypatch):
    _serve(monkeypatch, chat.url, ["qwen3:8b"])
    over = client.post("/api/local-models/try", json={"prompt": "x" * (localtry.MAX_PROMPT_CHARS + 1)})
    assert over.status_code == 422 and "2000" in over.json()["detail"]
    edge = client.post("/api/local-models/try", json={"prompt": "x" * localtry.MAX_PROMPT_CHARS})
    assert edge.status_code == 200
    empty = client.post("/api/local-models/try", json={"prompt": "   "})
    assert empty.status_code == 422 and "Type something" in empty.json()["detail"]
    assert len(chat.seen) == 1, "only the one inside the limit reached the server"


def test_no_server_is_a_409_that_says_to_start_one(client):
    # the suite's default: nothing answers anywhere
    answer = client.post("/api/local-models/try", json={"prompt": "hi"})
    assert answer.status_code == 409
    assert "No local model server is running" in answer.json()["detail"]


def test_a_server_with_no_model_is_a_409_that_says_to_download_one(chat, client, monkeypatch):
    _serve(monkeypatch, chat.url, [])
    answer = client.post("/api/local-models/try", json={"prompt": "hi"})
    assert answer.status_code == 409 and "no chat model" in answer.json()["detail"]
    assert chat.seen == []


def test_a_model_the_server_does_not_hold_is_a_409_that_lists_what_it_has(chat, client, monkeypatch):
    _serve(monkeypatch, chat.url, ["qwen3:8b"])
    answer = client.post("/api/local-models/try", json={"prompt": "hi", "model": "llama3:70b"})
    assert answer.status_code == 409
    assert "llama3:70b is not loaded" in answer.json()["detail"] and "qwen3:8b" in answer.json()["detail"]
    assert chat.seen == []


def test_a_slow_model_is_a_timeout_in_words(chat, client, monkeypatch):
    chat.mode["delay"] = 1.5
    monkeypatch.setattr(localtry, "TIMEOUT_SECONDS", 0.3)
    _serve(monkeypatch, chat.url, ["qwen3:8b"])
    answer = client.post("/api/local-models/try", json={"prompt": "hi"})
    assert answer.status_code == 504
    assert "did not answer" in answer.json()["detail"]


def test_a_server_that_went_away_is_a_502_that_says_it_is_down(client, monkeypatch):
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{one.getsockname()[1]}"
    _serve(monkeypatch, dead, ["qwen3:8b"])
    answer = client.post("/api/local-models/try", json={"prompt": "hi"})
    assert answer.status_code == 502
    assert "not reachable" in answer.json()["detail"]


def test_a_server_that_refuses_is_a_502_with_its_status(chat, client, monkeypatch):
    chat.mode["status"] = 400
    _serve(monkeypatch, chat.url, ["qwen3:8b"])
    answer = client.post("/api/local-models/try", json={"prompt": "hi"})
    assert answer.status_code == 502 and "400" in answer.json()["detail"]


def test_the_installed_list_names_the_recommended_model_so_the_window_holds_none(client, monkeypatch):
    from app import localplane, modelpull

    monkeypatch.setattr(modelpull, "ollama_base", lambda path=None: "http://ollama.test")
    monkeypatch.setattr(modelpull, "installed", lambda base: [{"name": f"{localplane.RECOMMENDED_MODEL}-it-q4_K_M"}])
    body = client.get("/api/local-models").json()
    assert body["recommended_model"] == localplane.RECOMMENDED_MODEL
    assert body["recommended_installed"] is True
    monkeypatch.setattr(modelpull, "ollama_base", lambda path=None: "")
    body = client.get("/api/local-models").json()
    assert body["recommended_installed"] is False and body["models"] == []
