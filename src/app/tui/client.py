"""How a terminal client reaches an engine — and how it starts one when there
is none. Used by both the operator TUI (`app/tui/app.py`) and the plain CLI's
HTTP-backed subcommands (`app/cli.py`: prefs, costs, sites, verify, drafts,
operations) — one client, so a fix to a call here is a fix both see.

**One API, two clients.** Everything this module calls is an endpoint the web
dashboard already calls. That is the whole reason a TUI is cheap here: the
interface layer is HTTP, so a second front end is a second *reader* of the same
surface rather than a second implementation of the same logic. It also makes
the TUI a standing test of whether that surface is complete — anything the TUI
cannot do without a new endpoint is something the API was not actually
exposing.

**Discovery, in the order that surprises a reader least.** An explicit `--url`
wins; then `KRIKO_URL`; then the fixed `EXTENSION_PORT`, because a running
desktop app is *always* serving there (that port exists precisely because a
browser extension cannot be told a random one) — so `kriko tui` with the app
open attaches to the app's own engine, same store, same jobs, same shell.

Only if nothing answers does this start an engine of its own, in-process, on an
OS-chosen port. That matters for the operator case this exists for: agent
operations must be drivable on a machine where the desktop shell will not open
at all, which is the situation that produced this TUI in the first place.

Stdlib `urllib` rather than `httpx`: the app's runtime dependencies are what a
reader's installer carries, and a terminal client that only ever talks to
127.0.0.1 does not justify adding one.
"""

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from app.web.settings import EXTENSION_PORT

#: How long any one call may take. Generous for a local socket, because
#: `/api/agenda` does real work on a large store; short enough that a hung
#: engine shows up as an error in the status bar rather than a frozen UI.
TIMEOUT = 30.0

#: Where to look for an engine already serving, in order.
DEFAULT_PORTS = (EXTENSION_PORT,)


class EngineError(RuntimeError):
    """A call failed, with whatever the engine said about it."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass
class Engine:
    """A base URL and the calls the TUI makes against it."""

    url: str
    #: Set when this process started the engine itself, for the status bar —
    #: "attached to the running app" and "started my own" are different facts
    #: about where a job will show up, and the operator needs to know which.
    owned: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ── the wire ────────────────────────────────────────────────────────

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            method=method,
            headers={"content-type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            raise EngineError(str(detail)[:400], error.code) from error
        except OSError as error:
            raise EngineError(f"{type(error).__name__}: {error}") from error
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError as error:
            raise EngineError(f"the engine answered with something that is not JSON") from error
        return parsed if isinstance(parsed, dict) else {"items": parsed}

    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self.request("POST", path, body if body is not None else {})

    def delete(self, path: str) -> dict:
        return self.request("DELETE", path)

    def put(self, path: str, body: dict | None = None) -> dict:
        return self.request("PUT", path, body if body is not None else {})

    # ── what the screens ask for ────────────────────────────────────────

    def health(self) -> dict:
        return self.get("/api/health")

    def planes(self) -> dict:
        return self.get("/api/research-planes")

    def agenda(self, limit: int = 60) -> dict:
        return self.get(f"/api/agenda?limit={int(limit)}")

    def jobs(self, limit: int = 60) -> dict:
        return self.get(f"/api/jobs?limit={int(limit)}")

    def job(self, job_id: str) -> dict:
        return self.get(f"/api/jobs/{job_id}")

    def packs(self) -> dict:
        return self.get("/api/packs")

    def operations(self, limit: int = 200) -> dict:
        """The live operations feed (`docs/AGENT_OPERATIONS.md`) — every door,
        newest first, so the operator can see agent-driven work regardless of
        whether it came in over MCP, a job, or HTTP."""
        return self.get(f"/api/operations?limit={int(limit)}")

    def research(self, subject_id: str, pack_id: str = "", backend: str = "") -> dict:
        """Start one subject's research. Backend empty = the engine decides.

        Deliberately no `budget_usd`: a TUI keystroke must not be able to start
        paid work. The engine's own default already refuses to pick the paid
        plane by omission, and this keeps that true from here too.
        """
        body = {"subject_id": subject_id, "backend": backend}
        if pack_id:
            body["pack_id"] = pack_id
        return self.post("/api/research", body)

    def agenda_run(self) -> dict:
        return self.post("/api/agenda/run")

    def cancel(self, job_id: str) -> dict:
        return self.post(f"/api/jobs/{job_id}/cancel")

    def retry(self, job_id: str) -> dict:
        return self.post(f"/api/jobs/{job_id}/retry")

    # ── the shell ───────────────────────────────────────────────────────

    def terminal_state(self, offset: int = 0) -> dict:
        return self.get(f"/api/terminal/state?offset={int(offset)}")

    def terminal_input(self, data: str) -> dict:
        return self.post("/api/terminal/input", {"data": data})

    def terminal_resize(self, cols: int, rows: int) -> dict:
        return self.post("/api/terminal/resize", {"cols": cols, "rows": rows})

    def terminal_close(self) -> dict:
        return self.post("/api/terminal/close")

    # ── the other screens the CLI can now also reach (`kriko` subcommands
    # for prefs/costs/sites/verify/drafts) — the same door, so a fix to one
    # of these endpoints is a fix both clients see. ─────────────────────

    def prefs(self) -> dict:
        return self.get("/api/prefs")

    def write_prefs(self, **fields: str) -> dict:
        return self.put("/api/prefs", {k: v for k, v in fields.items() if v is not None})

    def costs(self) -> dict:
        return self.get("/api/costs")

    def sites(self) -> dict:
        return self.get("/api/sites")

    def register_site(self, host: str, url: str = "", pack_id: str = "") -> dict:
        return self.post(f"/api/sites/{host}/register", {"url": url, "pack_id": pack_id})

    def forget_site(self, host: str) -> dict:
        return self.delete(f"/api/sites/{host}")

    def verify(self, pack_id: str = "", subject_id: str = "", limit: int = 50) -> dict:
        return self.post(
            "/api/verify",
            {"pack_id": pack_id, "subject_id": subject_id, "limit": limit},
        )

    def fact_checks(self, verdict: str = "", limit: int = 200) -> dict:
        path = f"/api/factcheck?limit={int(limit)}"
        if verdict:
            path += f"&verdict={verdict}"
        return self.get(path)

    def drafts(self) -> dict:
        return self.get("/api/packs/drafts")

    def draft(self, slug: str) -> dict:
        return self.get(f"/api/packs/drafts/{slug}")

    def amend_draft(self, slug: str, note: str = "") -> dict:
        return self.post(f"/api/packs/drafts/{slug}/amend", {"note": note})

    def build_draft(self, slug: str) -> dict:
        return self.post(f"/api/packs/drafts/{slug}/build")

    def install_draft(self, slug: str) -> dict:
        return self.post(f"/api/packs/drafts/{slug}/install")

    def discard_draft(self, slug: str) -> dict:
        return self.delete(f"/api/packs/drafts/{slug}")


def reachable(url: str) -> bool:
    try:
        Engine(url).health()
    except EngineError:
        return False
    return True


def attach(url: str = "") -> Engine | None:
    """An engine that is already serving, or `None`.

    Never starts one — `connect` decides that, so a caller who wants "attach or
    fail" (a test, a script) can have it without the side effect.
    """
    candidates = [url] if url else []
    if not candidates and os.environ.get("KRIKO_URL"):
        candidates.append(os.environ["KRIKO_URL"].rstrip("/"))
    candidates += [f"http://127.0.0.1:{port}" for port in DEFAULT_PORTS]
    for candidate in candidates:
        candidate = candidate.rstrip("/")
        if reachable(candidate):
            return Engine(candidate)
    return None


def serve_in_thread(settings=None) -> Engine:
    """Start an engine inside this process, on a port the OS picks.

    A daemon thread rather than a subprocess: there is no second binary to find,
    no port line to parse, and nothing to orphan — the classic failure of the
    desktop shell's sidecar is exactly what this avoids by not having one.

    The port is bound *before* the thread starts and handed to uvicorn, because
    asking the OS for a free port and then hoping it is still free is the race
    `app/sidecar.py` documents at length.
    """
    import socket

    import uvicorn

    from app.web.app import create_app
    from app.web.settings import Settings

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    app = create_app(settings or Settings())
    server = uvicorn.Server(
        uvicorn.Config(app, log_config=None, log_level="warning", access_log=False)
    )
    thread = threading.Thread(
        target=lambda: server.run(sockets=[sock]), daemon=True, name="kriko-tui-engine"
    )
    thread.start()
    return Engine(f"http://127.0.0.1:{port}", owned=True)


def connect(url: str = "", allow_start: bool = True, settings=None) -> Engine:
    """Attach to a running engine, or start one. Raises if neither works."""
    found = attach(url)
    if found is not None:
        return found
    if url:
        # An explicit address that does not answer is a typo or a dead app, and
        # silently starting a *different* engine would hide both.
        raise EngineError(f"nothing is serving at {url}")
    if not allow_start:
        raise EngineError("no engine is running, and starting one was not allowed")
    engine = serve_in_thread(settings)
    for _ in range(100):
        if reachable(engine.url):
            return engine
        threading.Event().wait(0.05)
    raise EngineError("started an engine and it never answered /api/health")
