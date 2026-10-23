"""Exercise urllib's real buffered socket, which differs from stream stubs."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

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
            # Keep the socket active without completing an SSE line. This
            # defeats a per-read timeout and exercises the stream's own clock.
            for _ in range(400):
                if release.wait(0.05):
                    break
                if ending != "done":
                    try:
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    except OSError:
                        break

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    outcome = []

    def read():
        try:
            outcome.append(_http.post_sse_or_why(
                f"http://127.0.0.1:{server.server_port}/stream", {}, {},
                0.3 if ending == "deadline" else 10,
                lambda _event: None, cancel_event=cancelled))
        except _http.StreamCancelled:
            outcome.append("cancelled")

    worker = threading.Thread(target=read, daemon=True)
    try:
        worker.start()
        assert entered.wait(3)
        if ending == "cancel":
            cancelled.set()
        # Leave scheduling headroom under the parallel Windows gate while
        # still requiring interruption well before the socket/peer's timeout.
        worker.join(3)
        assert not worker.is_alive(), "a blocked buffered read outlived its caller"
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
