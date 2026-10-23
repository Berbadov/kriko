"""Exercise urllib's real buffered socket, which differs from stream stubs."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest

from app.providers import _http


@pytest.mark.parametrize("ending", ["deadline", "cancel", "done"])
def test_a_stalled_sse_socket_stops_at_deadline_or_cancel(ending):
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"ok":true}\n\ndata: [DONE]\n\n'
                             if ending == "done" else b'data: {"partial":')
            self.wfile.flush()
            entered.set()
            release.wait(4)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    outcome = []

    def read():
        try:
            outcome.append(_http.post_sse_or_why(
                f"http://127.0.0.1:{server.server_port}/stream", {}, {},
                0.2 if ending == "deadline" else 3,
                lambda _event: None, cancel_event=cancelled))
        except _http.StreamCancelled:
            outcome.append("cancelled")

    worker = threading.Thread(target=read, daemon=True)
    try:
        began = time.monotonic()
        worker.start()
        assert entered.wait(1)
        if ending == "cancel":
            cancelled.set()
        worker.join(1)
        assert not worker.is_alive(), "a blocked buffered read outlived its caller"
        assert time.monotonic() - began < 1
        if ending == "cancel":
            assert outcome == ["cancelled"]
        elif ending == "done":
            assert outcome == [(1, "")]
        else:
            assert "budget" in outcome[0][1] or "unreachable" in outcome[0][1]
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(4)
