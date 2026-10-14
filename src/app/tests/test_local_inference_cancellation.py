import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import agentresources
from app.providers.local_agent import LocalAsker
from app.providers.local_inference import OpenAICompatSocket


class _Cancelled(Exception):
    pass


@pytest.mark.parametrize("structured", [False, True])
def test_cancel_interrupts_silent_local_completion_and_releases_permit(monkeypatch, structured):
    monkeypatch.setenv("KRIKO_MAX_LOCAL_INFERENCE", "1")
    first_started = threading.Event()
    let_server_finish = threading.Event()
    calls = 0

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal calls
            size = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(size) or b"{}")
            calls += 1
            if calls == 1:
                first_started.set()
                if request.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    event = {"choices": [{"delta": {"content": "partial"}}]}
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", "100")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(b"{")
                    self.wfile.flush()
                let_server_finish.wait(3)
                return

            if request.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                event = {"choices": [{"delta": {"content": "recovered"},
                                      "finish_reason": "stop"}]}
                self.wfile.write(("data: " + json.dumps(event) + "\n\n" +
                                  "data: [DONE]\n\n").encode())
            else:
                body = json.dumps({"choices": [{"message": {"content": "recovered"},
                                                "finish_reason": "stop"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    socket = OpenAICompatSocket(f"http://127.0.0.1:{server.server_port}", "fixture",
                                timeout=10,
                                response_json_schema={"type": "object"} if structured else "")
    owner = LocalAsker(socket, socket, None, None, model="fixture", search_provider="fixture")
    cancelled = threading.Event()
    owner_thread = threading.get_ident()
    check_calls = 0

    def check_cancelled():
        nonlocal check_calls
        assert threading.get_ident() == owner_thread, "Progress.check must stay on its SQLite owner thread"
        check_calls += 1
        if cancelled.is_set():
            raise _Cancelled()

    owner.check_cancelled = check_cancelled
    started = time.monotonic()
    try:
        if structured:
            threading.Timer(0.15, cancelled.set).start()
            with pytest.raises(_Cancelled):
                owner._complete.stream("prompt", lambda _piece: None)
        else:
            def on_text(_piece):
                cancelled.set()

            with pytest.raises(_Cancelled):
                owner._complete.stream("prompt", on_text)
        elapsed = time.monotonic() - started
        assert elapsed < 2, f"cancel took {elapsed:.3f}s after {check_calls} owner-thread checks"
        assert first_started.is_set()
        assert check_calls >= 2

        # The silent response held the local inference and outbound permits.
        # Closing it must free both before another local completion begins.
        with agentresources.slot("inference", timeout=0.25):
            pass
        cancelled.clear()
        owner._complete.stream("prompt", lambda _piece: None)
        assert calls == 2
    finally:
        let_server_finish.set()
        server.shutdown()
        server.server_close()
