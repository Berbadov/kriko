"""The local dashboard.

    python -m app.web            # http://127.0.0.1:8787

An app *factory*, not a module-level `app`. That is what makes the routers
testable and what unblocked backlog B28: a test builds an app pointed at a
temporary store, and two tests can run against two stores at once. The old hub
computed its paths as import-time constants, which meant neither was possible.

Binds to 127.0.0.1 by design. Kriko is local-first — there is no account system,
no authentication and no authorisation, because there is nothing multi-tenant to
protect. Serving this on 0.0.0.0 would expose an unauthenticated pack-uninstall
endpoint to the network, so the default host is not a preference.
"""

import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.web.jobs import JobRunner
from app.web.routers import (
    agent,
    analyze,
    control,
    extension,
    focus,
    health,
    history,
    jobs,
    marks,
    packs,
    query,
    subjects,
)
from app.web import state
from app.version import app_version, installed_versions
from app.web.settings import EXTENSION_PORT, Settings
from app.web.tasks import HANDLERS
from kriko.store.db import SCHEMA_VERSION

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A job that was running when the process died is not running now. Saying
    # so at startup is the difference between durable status and a row that
    # lies forever.
    app.state.jobs.recover()
    yield
    app.state.jobs.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Kriko", docs_url="/api/docs", redoc_url=None, lifespan=lifespan
    )
    app.state.settings = settings or Settings.from_env()

    for router in (
        agent.router,
        packs.router,
        query.router,
        subjects.router,
        analyze.router,
        control.router,
        extension.router,
        focus.router,
        health.router,
        history.router,
        jobs.router,
        marks.router,
    ):
        app.include_router(router)

    # One runner per app, built here so a test app gets its own pool pointed at
    # its own temporary app.sqlite.
    app.state.jobs = JobRunner(app.state.settings, HANDLERS)

    # ── the extension announces itself by calling ────────────────────────
    #
    # There is no registration handshake and there should not be one: the
    # extension's job is to answer questions about a listing, not to check in.
    # But a browser stamps `Origin: chrome-extension://<id>` on every request
    # its extensions make, and nothing else on this machine can produce that
    # header. So the sighting is a side effect of the extension doing its
    # actual work — which makes it the one piece of evidence that cannot be
    # true while the install is broken.
    #
    # Guarded on the prefix so an ordinary request never opens app.sqlite, and
    # swallowing failures so this can never be the reason a lookup 500s: the
    # extension is waiting on that response, and losing a status detail is
    # cheaper than losing the answer.
    @app.middleware("http")
    async def note_the_extension(request: Request, call_next):
        origin = request.headers.get("origin", "")
        if origin.startswith(("chrome-extension://", "moz-extension://")):
            try:
                conn = state.connect(app.state.settings.app_state_path)
                try:
                    state.record_extension(conn, origin)
                finally:
                    conn.close()
            except Exception:
                pass
        return await call_next(request)

    # ── an unhandled error says what it was ──────────────────────────────
    #
    # Everything above is a local process with exactly one reader, who has no
    # terminal, no log viewer and no way to reach the traceback that FastAPI
    # writes to a stderr the desktop shell swallows. "Could not load this
    # view: 500: Internal Server Error" is all they get, on every view at
    # once, with nothing to send anyone.
    #
    # That is what happened to 0.3.1: a cross-thread SQLite connection made
    # every store-backed view fail, and the message named neither SQLite nor
    # threads. The connection bug is fixed in `kriko.store.db`; this exists so
    # the *next* one is legible, because a local app has no operator to page
    # and the reader is the only instrument we have.
    #
    # Safe to return the detail because there is nothing here to leak to:
    # 127.0.0.1, no accounts, no other tenant. The one caller that is not the
    # reader is the browser extension, which already runs on the reader's own
    # machine on their behalf.
    @app.exception_handler(Exception)
    async def explain_the_failure(request: Request, exc: Exception):
        trace = traceback.format_exception(type(exc), exc, exc.__traceback__)
        print("".join(trace), file=sys.stderr, flush=True)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"{type(exc).__name__}: {exc}",
                "where": request.url.path,
                # The last few frames, not the whole stack: enough to name the
                # module that failed in a copyable line, without pasting the
                # ASGI plumbing into the reader's screen.
                "trace": [line.rstrip() for line in trace[-6:]],
            },
        )

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/health")
    def liveness():
        return {
            "ok": True,
            "store": str(app.state.settings.store_path),
            "analysis_log": str(app.state.settings.analysis_log_path),
            # Two SQLite files is a thing an operator has to know about, so
            # the endpoint that names one names both.
            "app_state": str(app.state.settings.app_state_path),
            # Three versions, never one. The binary updates through Tauri, a
            # pack updates through the engine, and the schema changes with
            # neither — a reader asked "what are you running" has to be able
            # to answer the question that was actually meant.
            "version": app_version(),
            "schema_version": SCHEMA_VERSION,
            "packs": installed_versions(app.state.settings.store_path),
            "releases_url": app.state.settings.releases_url,
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


def main(argv=None) -> int:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="app.web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=EXTENSION_PORT)
    parser.add_argument("--store", default=None)
    args = parser.parse_args(argv)

    overrides = {"store_path": Path(args.store)} if args.store else {}
    uvicorn.run(
        create_app(Settings.from_env(**overrides)),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
