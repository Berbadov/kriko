import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.providers import network


def test_loopback_ignores_hostile_proxy_environment(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"direct")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.server_port}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    try:
        with network.urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
            assert response.read() == b"direct"
    finally:
        server.shutdown()
        proxy.shutdown()
        thread.join(1)
        proxy_thread.join(1)
        server.server_close()
        proxy.server_close()


def test_remote_requests_keep_urllib_environment_policy(monkeypatch):
    seen = []

    class Response:
        def close(self):
            pass

    def open_remote(request, timeout=None):
        seen.append((request, timeout, os.environ.get("HTTPS_PROXY")))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", open_remote)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    with network.urlopen("https://service.example/api", timeout=3):
        pass
    assert seen[0][0] == "https://service.example/api"
    assert seen[0][1] == 3
    assert seen[0][2] == "http://proxy.example:8080"


def test_network_kind_alias_acquires_one_outbound_slot(monkeypatch):
    from app.providers import network as module

    acquired = []

    class Permit:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(module, "slot", lambda kind, *args, **kwargs:
                        acquired.append(kind) or Permit())

    class Response:
        def close(self):
            pass

    with module.urlopen("https://example.test", kind="network",
                        opener=lambda *_args, **_kwargs: Response()):
        pass
    assert acquired == ["outbound"]
