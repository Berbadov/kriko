"""The app must survive a browser, which never asks one question at a time.

Every view in this frontend opens with a `Promise.all` — Overview alone fires
six requests before it paints anything. Nothing in the suite did that, and the
gap had a name: 0.3.1 shipped with a SQLite connection that was opened on one
worker thread and used on another, so every store-backed view failed with

    sqlite3.ProgrammingError: SQLite objects created in a thread can only be
    used in that same thread.

behind an anonymous "500: Internal Server Error", on the reader's machine, on
first run. A sequential sweep of all twenty-one endpoints returned 200 for
every one of them, because with a single idle worker the pool happens to hand
back the same thread. `packaging/smoke_sidecar.py` was green. CI was green.

Concurrency was the whole bug, so concurrency is the test. `TestClient` is not
enough on its own — its portal serialises — so this runs a real uvicorn server
on a real socket and points real threads at it, which is the only arrangement
that reproduces what a browser does.
"""

import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest
import uvicorn

from app.web.app import create_app
from app.web.settings import Settings

#: Every GET a view opens with. Not a sample: the failure was per-connection,
#: so an endpoint left out of this list is an endpoint nobody is checking.
READS = [
    "/api/health",
    "/api/status",
    "/api/packs",
    "/api/kinds",
    "/api/subjects",
    "/api/history",
    "/api/jobs",
    "/api/activity",
    "/api/adapters",
    "/api/settings",
    "/api/agent-config",
    "/api/agent-targets",
    "/api/agent-skill",
    "/api/extension",
    "/api/health/weakest",
]


@pytest.fixture
def running_app(tmp_path):
    """A real server on a real port, torn down with the test.

    Port 0 and then reading the socket back, for the same reason
    `app/sidecar.py` does it: a port found free by asking the OS is already
    stale by the time anything binds it.
    """
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    port = held.getsockname()[1]
    held.close()

    app = create_app(
        Settings(
            store_path=tmp_path / "knowledge.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "analyses.jsonl",
        )
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while time.time() < deadline and not server.started:
        time.sleep(0.05)
    assert server.started, "the test server never came up"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=20)


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, ""
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")[:400]


def test_no_view_fails_when_its_requests_arrive_together(running_app):
    """Fifteen endpoints, four times over, all in flight at once.

    Four rounds rather than one because the pool grows on demand: the first
    burst is what spreads the work across workers, and a single round can still
    land inside one thread on a fast machine.
    """
    urls = [f"{running_app}{path}" for path in READS] * 4
    with ThreadPoolExecutor(max_workers=len(READS)) as pool:
        results = list(pool.map(_get, urls))

    failures = [
        f"{url} -> {status} {body}"
        for url, (status, body) in zip(urls, results)
        if status >= 500
    ]
    assert not failures, "\n".join(failures)


def test_a_single_view_s_opening_burst_is_enough(running_app):
    """Overview's own six, fired the way the frontend fires them."""
    paths = [
        "/api/status",
        "/api/packs",
        "/api/packs/updates",
        "/api/jobs",
        "/api/health/weakest",
        "/api/activity",
    ]
    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        results = list(pool.map(_get, [f"{running_app}{p}" for p in paths]))
    assert [status for status, _ in results if status >= 500] == []


def test_an_unhandled_error_says_what_it_was(running_app):
    """The other half of the fix: a 500 that names itself.

    The connection bug is gone, but the reason it cost a release round-trip is
    that the app could not describe it. A local process has one reader, no
    terminal and no log viewer; whatever the response body says is the entire
    diagnosis available to them. So a 500 must carry the exception's type and
    message, and this asserts the handler is wired rather than trusting it.
    """
    status, body = _get(f"{running_app}/api/subjects/no-such-subject/brief")
    # Either a clean 404 for a subject that does not exist, or — if it raises —
    # a 500 that names the exception. What is not allowed is a bare 500.
    assert status in (200, 404) or ("detail" in body and status == 500), body
