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

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.web.jobs import JobRunner
from app.web.routers import (
    analyze,
    control,
    health,
    history,
    jobs,
    packs,
    query,
    subjects,
)
from app.web.settings import EXTENSION_PORT, Settings
from app.web.tasks import HANDLERS

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
        packs.router,
        query.router,
        subjects.router,
        analyze.router,
        control.router,
        health.router,
        history.router,
        jobs.router,
    ):
        app.include_router(router)

    # One runner per app, built here so a test app gets its own pool pointed at
    # its own temporary app.sqlite.
    app.state.jobs = JobRunner(app.state.settings, HANDLERS)

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
