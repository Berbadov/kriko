"""A finished local run gives the model's memory back to the host.

The reader's words: "after the local agent run vram allocation isnt cleared
and causing performance issues; app should not cause any performance issues in
hosts computer when its in background". Ollama holds a model for five minutes
after its last request unless told otherwise, so Kriko tells it: when the last
running job ends, every model this process ran is unloaded (`keep_alive` 0).
The server here is a loopback stub; nothing is loaded and nothing leaves
127.0.0.1.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import local_inference
from app.web import state
from app.web.jobs import JobRunner


class Server:
    def __init__(self):
        self.unloads: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/generate":
                    server.unloads.append(body)
                    reply = {"model": body["model"], "done": True, "done_reason": "unload"}
                else:
                    reply = {"choices": [{"message": {"content": "[]"}}]}
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def server():
    local_inference.release()
    one = Server()
    yield one
    one.http.shutdown()
    one.http.server_close()


def test_release_unloads_every_model_that_was_run_once(server):
    local_inference.OpenAICompatSocket(server.url, "m:3b").complete("hello")
    local_inference.OpenAICompatSocket(server.url + "/v1", "m:3b").complete("again")
    assert local_inference.release() == ["m:3b"]
    assert server.unloads == [{"model": "m:3b", "keep_alive": 0}]
    # Nothing ran since: nothing to let go, and the server is not asked again.
    assert local_inference.release() == []
    assert len(server.unloads) == 1


def test_a_server_that_cannot_unload_does_not_fail_anything():
    local_inference.release()
    local_inference._hold("http://127.0.0.1:9", "gone")
    assert local_inference.release(timeout=1) == []


def test_the_last_job_to_end_lets_go_and_not_before(tmp_path, server):
    class Settings:
        app_state_path = tmp_path / "app.sqlite"
        store_path = tmp_path / "knowledge.sqlite"

    state.connect(Settings.app_state_path).close()
    first_running, release_first = threading.Event(), threading.Event()
    idle = threading.Event()
    seen_at_idle = []

    def first(settings, params, progress):
        local_inference.OpenAICompatSocket(server.url, "m:3b").complete("x")
        first_running.set()
        release_first.wait(5)
        return {}

    def quick(settings, params, progress):
        return {}

    def on_idle():
        seen_at_idle.append(len(server.unloads))
        local_inference.release()
        idle.set()

    runner = JobRunner(Settings, {"first": first, "quick_look": quick}, on_idle=on_idle)
    try:
        runner.submit("first", {})
        assert first_running.wait(5)
        # A quick job ending while the long one still runs is not idle.
        runner.submit("quick_look", {})
        assert not idle.wait(0.5)
        assert server.unloads == []
        release_first.set()
        assert idle.wait(5)
        assert seen_at_idle == [0]
        assert server.unloads == [{"model": "m:3b", "keep_alive": 0}]
    finally:
        release_first.set()
        runner.shutdown(wait=True)
