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

import logging
import sys
import traceback
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import extension as ext, logs
from app.web import origins, pipeline
from app.web.jobs import JobRunner
from app.web.routers import (
    agent,
    analyze,
    control,
    extension,
    factcheck,
    focus,
    health,
    history,
    jobs,
    marks,
    packs,
    pipeline as pipeline_router,
    query,
    subjects,
    submissions,
)
from app.web import state
from app.version import app_version, installed_versions
from app.web.settings import EXTENSION_PORT, Settings
from app.web.tasks import HANDLERS
from kriko.store.db import SCHEMA_VERSION

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"


def _shipped_extension_version() -> str:
    """What the app carries, or "" where it carries nothing.

    A bundle built without the extension is a packaging shape, not a fault —
    see `extension.source_dir` — so this answers rather than raising on the
    endpoint the shell polls before it will show a window.
    """
    source = ext.source_dir()
    return ext.version(source) if source else ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A job that was running when the process died is not running now. Saying
    # so at startup is the difference between durable status and a row that
    # lies forever.
    app.state.jobs.recover()
    # And the same for the pipeline's own rows. A run left `running` is a run
    # that was killed — the process cannot resume one it has no memory of, and
    # a row that says `running` forever renders as a pipeline that never
    # finishes. Guarded, because a reconciliation failure must not be the
    # reason the app will not start.
    try:
        conn = state.connect(app.state.settings.app_state_path)
        try:
            stranded = pipeline.mark_interrupted(conn)
        finally:
            conn.close()
        if stranded:
            log.warning("marked %d stranded pipeline run(s) interrupted", stranded)
    except Exception:
        log.warning("could not reconcile pipeline runs at startup", exc_info=True)
    yield
    app.state.jobs.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Kriko", docs_url="/api/docs", redoc_url=None, lifespan=lifespan
    )
    app.state.settings = settings or Settings.from_env()

    # ── the log has to be somewhere this process can actually write ───────
    #
    # `default_analysis_log()` prefers the checkout, which is right for a
    # developer's data and wrong the moment that directory is owned by
    # somebody else — which is how every analysis append on the machine this
    # was written on failed for two months into a root-owned `logs/`, through
    # a `log.warning` that no configured handler was listening to.
    #
    # So: resolve it, fall back to ~/.kriko rather than refuse to start, and
    # carry the reason out to /api/health. Falling back is the fail-open rule
    # the data path already follows; carrying the reason is the part that was
    # missing.
    logs.configure()
    resolved, why = logs.resolve_writable(
        app.state.settings.analysis_log_path,
        logs.KRIKO_HOME / "logs" / "analyses.jsonl",
    )
    if why is not None:
        log.warning(
            "analysis log %s is not writable, using %s (%s)",
            app.state.settings.analysis_log_path,
            resolved,
            why,
        )
        app.state.settings = replace(app.state.settings, analysis_log_path=resolved)
    app.state.analysis_log_problem = why

    for router in (
        agent.router,
        packs.router,
        pipeline_router.router,
        query.router,
        subjects.router,
        analyze.router,
        control.router,
        extension.router,
        factcheck.router,
        focus.router,
        health.router,
        history.router,
        jobs.router,
        marks.router,
        submissions.router,
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
    # The version rides along for the same reason. Asking the extension to
    # check in on a schedule would be a second clock to keep wound; a header
    # on work it was going to do anyway cannot go stale, cannot be forgotten,
    # and cannot be true while the install is broken. An extension too old to
    # send it leaves the column blank — which is itself the answer, because
    # every version that sends anything is newer than one that cannot.
    @app.middleware("http")
    async def note_the_extension(request: Request, call_next):
        origin = request.headers.get("origin", "")
        if origin.startswith(("chrome-extension://", "moz-extension://")):
            try:
                conn = state.connect(app.state.settings.app_state_path)
                try:
                    state.record_extension(
                        conn,
                        origin,
                        request.headers.get(ext.VERSION_HEADER, ""),
                    )
                finally:
                    conn.close()
            except Exception:
                pass
        response = await call_next(request)
        # And the other direction, on the same ride. The extension learns the
        # floor from the answer to a request it was already making — no second
        # endpoint, no poll, no third clock, and nothing to go stale between
        # winds. Exposed explicitly because a header the browser will not let
        # a caller read is a header that does not exist; the worker's own
        # fetches are exempt from CORS via `host_permissions`, but the
        # allowlist is what makes that not a thing to remember.
        response.headers[ext.MINIMUM_HEADER] = ext.MINIMUM_VERSION
        response.headers["access-control-expose-headers"] = ext.MINIMUM_HEADER
        return response

    # ── who is allowed to ask ────────────────────────────────────────────
    #
    # Registered *last* and therefore outermost: `add_middleware` inserts at
    # the front of the list, so the middleware added latest is the one a
    # request meets first. A refused request must not record an extension
    # sighting, open app.sqlite, or reach a router — so nothing may sit
    # above this, and test_origins.py asserts the position rather than
    # trusting a comment about it.
    #
    # `app/web/origins.py` carries the reasoning — the short version is that
    # binding 127.0.0.1 protects the port from the network and not from the
    # browser, and 8787 is a constant published in this repository.
    @app.middleware("http")
    async def only_from_here(request: Request, call_next):
        why = origins.refuse(
            request.headers.get("origin"), request.headers.get("host")
        )
        if why is not None:
            # Logged, because the reader will see a view fail and this is the
            # only place that says why. Warning rather than error: a page
            # probing localhost is the system working, not a fault.
            log.warning(
                "refused %s %s: %s", request.method, request.url.path, why
            )
            return JSONResponse({"detail": why}, status_code=403)
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
        # Both, on purpose: the file is what the reader sends us, and stderr
        # is what the desktop shell captured before the file existed — and
        # still the only surface if `logs.configure()` could not open one.
        log.error("unhandled error at %s", request.url.path, exc_info=exc)
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
            # Not decoration: a null `log_file` or a non-null `*_problem` is
            # the difference between "no bug reports came in" and "no bug
            # report could have come in". Settings renders both.
            "analysis_log_problem": app.state.analysis_log_problem,
            "log_file": str(logs.active_path()) if logs.active_path() else None,
            "log_problem": logs.failure_reason(),
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
            # ── what the extension has to know, and could not ask ─────
            #
            # Both of these were knowable and neither was reachable, which is
            # how "Open in App" came to open a browser tab for two entirely
            # different reasons that looked identical from the outside.
            #
            # `shell_attached`: is anything reading our stdout? Without it a
            # headless sidecar and a supervised one are the same server.
            #
            # `port_is_ours`: did *this* process win EXTENSION_PORT? If a
            # stale sidecar holds 8787, the extension talks to the old process
            # and a fresh install looks perfect while reaching nothing. It was
            # already on /api/extension, which is the page a reader opens
            # after they have decided something is broken — too late to be the
            # thing that tells them.
            "shell_attached": bool(app.state.settings.shell_attached),
            "extension_port": EXTENSION_PORT,
            # The extension's half of the handshake. It reads this on its own
            # schedule and compares its manifest against the floor, because
            # the app cannot make the browser do anything — only say what it
            # needs. /api/health rather than /api/extension: the extension
            # already polls this one, and a compatibility check that needs a
            # second request is a check that fails when the first one does.
            "minimum_extension_version": ext.MINIMUM_VERSION,
            "extension_version": _shipped_extension_version(),
            "port_is_ours": bool(app.state.settings.extension_port_bound),
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
