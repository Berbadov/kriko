import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import network


@pytest.fixture(autouse=True)
def isolated_engine_cooldowns(monkeypatch):
    # The parallel-engine tests require both engines to be eligible. Another
    # test's process-wide cooldown must not silently turn them into one-engine tests.
    from app.providers import openserp
    monkeypatch.setattr(openserp, "_failed_at", {})


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


def test_openserp_search_timeout_can_be_shortened_by_the_caller(monkeypatch):
    from app.providers import openserp

    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"results": []}'

    monkeypatch.setattr(openserp.network, "urlopen",
                        lambda *args, **kwargs: seen.append(kwargs) or Response())
    search = openserp.searcher(timeout=45.0)
    search("default")
    search("short", timeout=8.0)
    assert [call["timeout"] for call in seen] == [45.0, 8.0]


def test_openserp_search_mode_can_be_chosen_per_instance_or_call(monkeypatch):
    from app.providers import openserp

    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"results": []}'

    def urlopen(request, **kwargs):
        seen.append(request.full_url)
        return Response()

    monkeypatch.setattr(openserp.network, "urlopen", urlopen)
    search = openserp.searcher(engine="bing", mode="any")
    search("default")
    search("override", mode="fast")
    assert "/bing/search?" in seen[0]
    assert "/mega/search?" in seen[1]
    assert "mode=fast" in seen[1]


def test_any_mode_keeps_usable_results_when_another_engine_only_returns_clickthroughs(monkeypatch):
    from app.providers import openserp

    seen = []
    replies = {
        "google": {"results": [{"url": "https://www.google.com/goto?url=opaque",
                                 "title": "Sponsored result", "domain": "google.com"}]},
        "bing": {"results": [{"url": "https://review.example/air-purifier",
                               "title": "Air purifier review", "domain": "review.example"}]},
    }

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            import json
            return json.dumps(self.payload).encode()

    def urlopen(request, **_kwargs):
        seen.append(request.full_url)
        return Response(replies["google" if "/google/" in request.full_url else "bing"])

    monkeypatch.setattr(openserp.network, "urlopen", urlopen)
    search = openserp.searcher(engine="google,bing", mode="any", timeout=8.0)

    assert search("air purifier reviews", 5) == [{
        "url": "https://review.example/air-purifier",
        "title": "Air purifier review", "site": "review.example",
    }]
    assert any("/bing/search?" in url for url in seen)
    assert all("/mega/" not in url for url in seen)


def test_any_mode_returns_a_useful_engine_without_waiting_for_a_stalled_one(monkeypatch):
    import json
    import threading
    import time
    from app.providers import openserp

    stalled = threading.Event()
    release = threading.Event()

    class Response:
        def __init__(self, request, check):
            self.request = request
            self.check = check

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            if "/google/" in self.request.full_url:
                stalled.set()
                release.wait(3)
                self.check()
                return b'{"results": []}'
            assert stalled.wait(1)
            return json.dumps({"results": [{"url": "https://maker.example/spec",
                                             "title": "Specification"}]}).encode()

    monkeypatch.setattr(openserp.network, "urlopen",
                        lambda request, **kwargs: Response(request, kwargs["check"]))
    search = openserp.searcher(engine="google,bing", mode="any", timeout=2)
    try:
        began = time.monotonic()
        assert search("a product")[0]["url"] == "https://maker.example/spec"
        assert time.monotonic() - began < 1.0
        assert not release.is_set()
    finally:
        release.set()


def test_any_mode_polls_cancellation_on_the_owner_thread_and_stops_workers(monkeypatch):
    import threading
    import pytest
    from app.providers import openserp

    owner = threading.get_ident()
    started = threading.Event()
    exited = threading.Event()

    class Response:
        def __init__(self, check):
            self.check = check

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            exited.set()

        def read1(self, _size):
            started.set()
            exited.wait(0.01)
            return b" "

    def check():
        assert threading.get_ident() == owner
        if started.is_set():
            raise RuntimeError("reader cancelled")

    monkeypatch.setattr(openserp.network, "urlopen",
                        lambda _request, **kwargs: Response(kwargs["check"]))
    search = openserp.searcher(engine="google,bing", mode="any", timeout=1)
    search.check_cancelled = check
    with pytest.raises(RuntimeError, match="reader cancelled"):
        search("a product")
    assert exited.wait(1)
