"""The local HTTP API.

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
import os
import sqlite3
import sys
import traceback
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app import agentconfig, agentskill, extension as ext, logs, packautoupdate
from app import modelcatalogue
from app.providers import local_inference
from app.web.settings import KRIKO_HOME
from app.web import origins, pipeline
from app.web.jobs import JobRunner
from app.web.knowledge_clock import KnowledgeClock
from app.web.routers import (
    agenda,
    agent,
    agent_runtime,
    analyze,
    appupdate,
    bench,
    buyer,
    chat,
    cloud,
    compare,
    compareq,
    control,
    extension,
    factcheck,
    favicon,
    focus,
    health,
    history,
    jobs,
    keys,
    live,
    local_models,
    machine,
    marks,
    operations,
    packs,
    prices,
    products,
    queue,
    prefs as prefs_router,
    query,
    research,
    sites,
    subjects,
    terminal,
)
from app.web import state
from app.version import app_version, installed_versions
from app.web.settings import EXTENSION_PORT, MAX_REQUEST_BYTES, Settings
from app.web.tasks import HANDLERS
from kriko.store.db import SCHEMA_VERSION, connect

log = logging.getLogger(__name__)

#: How many extension origins this process remembers. One dict entry per
#: origin the caller names; a native client can name as many as it likes.
EXTENSION_SIGHTINGS_MAX = 16


def _record_sighting(app_state_path, origin: str, version: str) -> None:
    """Write one extension sighting. Blocking, so callers run it off the loop."""
    conn = state.connect(app_state_path)
    try:
        state.record_extension(conn, origin, version)
    finally:
        conn.close()


def _store_is_readable(path) -> bool:
    """Can the engine's own store be opened and queried right now?

    A boolean, not a message: `/api/health` is polled by the shell and by the
    extension, and a health check that reports detail costs every poll for it.
    "The file exists" is not the question — a locked or corrupt store exists and
    cannot answer, which is the state a reader sees as "Kriko knows nothing".
    """
    try:
        conn = connect(path)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001 — a health answer, never a crash
        return False


def _job_capacity(runner) -> dict:
    """How busy the job runner is, without leaking its internals.

    The runner has answered this since the jobs screen needed it
    (`JobRunner.concurrency`); the health endpoint is the other place a reader
    and the shell's watchdog look, and it did not.
    """
    try:
        return runner.concurrency()
    except Exception:  # noqa: BLE001
        return {"running": 0, "queued": 0, "concurrency": 0, "agent_slots": 0}


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
    # The extension the browser loads, brought up to the one this app carries
    # (B151). The extension reloads itself when the digest below is not its
    # own, so an app update reaches the browser without the reader's hands.
    app.state.extension_staged_digest = ""
    app.state.firefox_staged_digest = ""
    try:
        target = ext.target_for(app.state.settings.store_path)
        if ext.refresh(ext.source_dir(), target):
            log.info("restaged the extension at %s", target)
        if (target / "manifest.json").is_file():
            app.state.extension_staged_digest = ext.content_digest(target)
        firefox = ext.target_for(app.state.settings.store_path, "firefox")
        if ext.refresh(ext.source_dir(), firefox, "firefox"):
            ext.package(firefox, firefox.with_suffix(".xpi"))
            log.info("restaged the Firefox add-on at %s", firefox)
        if (firefox / "manifest.json").is_file():
            app.state.firefox_staged_digest = ext.content_digest(firefox)
    except Exception:
        log.warning("could not refresh the staged extension", exc_info=True)

    # The reader's own price list, put where they can edit it. Copied once and
    # never again, so a correction they made survives every update — and
    # guarded like everything else here: a missing price costs a cost report,
    # never a startup.
    try:
        modelcatalogue.install_default(KRIKO_HOME)
    except OSError:
        log.warning("could not write the model catalogue", exc_info=True)
    # A job that was running when the process died is not running now. Saying
    # so at startup is the difference between durable status and a row that
    # lies forever.
    app.state.jobs.recover()
    # The same for the research queue: a product left being researched when the
    # app closed has no worker coming back for it, so it waits again, with why.
    queue_conn = state.connect(app.state.settings.app_state_path)
    try:
        state.recover_queue(queue_conn)
    finally:
        queue_conn.close()
    # And the same for the pipeline's own rows. A run left `running` is a run
    # that was killed — the process cannot resume one it has no memory of, and
    # a row that says `running` forever renders as a pipeline that never
    # finishes. Guarded, because a reconciliation failure must not be the
    # reason the app will not start.
    try:
        conn = state.connect(app.state.settings.app_state_path)
        try:
            stranded = pipeline.mark_interrupted(conn)
            # And the operations feed, for the same reason and with one extra:
            # these rows are written by the *MCP process*, which this one does
            # not supervise. A tool call that died with that process would
            # otherwise read as still running for the life of this install.
            state.interrupt_running_operations(conn)
        finally:
            conn.close()
        if stranded:
            log.warning("marked %d stranded pipeline run(s) interrupted", stranded)
    except Exception:
        log.warning("could not reconcile pipeline runs at startup", exc_info=True)
    # The protocol an agent reads has to follow the code and the packs.
    #
    # The skill is generated from both and was written exactly once — when the
    # reader pressed Connect. So an overhauled protocol, a tool that did not
    # exist last month, or a pack that updated yesterday reached the app and
    # never reached the agent, and "you did not change the skill text" was a
    # correct observation about the reader's own machine.
    #
    # Only harnesses already wired are touched (a file that is there and out of
    # date), and every failure is swallowed: a read-only home directory is a
    # row on the Agents screen, never a reason the app will not start.
    try:
        # Only if there is a store to read. Opening one *creates* it, and an
        # app that conjures an empty knowledge database on every start is an
        # app that has made a fact out of a side effect — `test_marks.py` holds
        # that line for the interface as a whole.
        if not Path(app.state.settings.store_path).exists():
            raise FileNotFoundError(app.state.settings.store_path)
        store = connect(app.state.settings.store_path)
        try:
            # The digest leaves the agenda snapshot out (`agentskill.digest`), so
            # whether a wired copy is stale can be answered from the protocol
            # alone, at ~0.2 ms against ~70 ms for the full render with the agenda
            # (the lookup tree over every claim). Startup pays for the agenda only
            # when something is going to be written.
            probe = agentskill.render(store) or ""
            if agentconfig.skill_needs_refresh(agentskill.SKILL_NAME, probe):
                # Rendered as the status check and the Update button render it, so
                # what startup writes is what they compare against (B157: it once
                # left out the agenda snapshot the other two put in).
                body = agent.skill_body(app.state.settings, store)
                refreshed = agentconfig.refresh_skills(agentskill.SKILL_NAME, body)
            else:
                refreshed = []
        finally:
            store.close()
        if refreshed:
            log.info("refreshed %d stale agent skill(s)", len(refreshed))
    except FileNotFoundError:
        pass
    except Exception:
        log.warning("could not refresh the agent skills", exc_info=True)

    # Installed packs follow the index weekly (B166), as a job that never
    # holds the window back. After `recover()` for the reason below: a job
    # submitted before it would be marked interrupted by it. Off under test
    # (KRIKO_NO_PACK_AUTOUPDATE) so entering a lifespan never reaches the
    # network.
    if not os.environ.get("KRIKO_NO_PACK_AUTOUPDATE"):
        try:
            packautoupdate.submit_if_due(app.state.settings, app.state.jobs)
        except Exception:
            log.warning("could not start the weekly pack update", exc_info=True)

    # Watched pages are re-read when the app opens and then on the engine's own
    # clock (`app/pricescheduler.py`), as jobs. Off under test with the pack
    # update (KRIKO_NO_PACK_AUTOUPDATE): both reach the network, and a test that
    # enters a lifespan must not.
    stop_price_clock = None
    if not os.environ.get("KRIKO_NO_PACK_AUTOUPDATE"):
        try:
            from app import pricescheduler

            sweeper = pricescheduler.Sweeper(
                app.state.settings.app_state_path,
                lambda: app.state.jobs.submit("price_sweep", {}))
            sweeper.tick()
            stop_price_clock = pricescheduler.start(sweeper)
        except Exception:
            log.warning("could not start the watched-page check", exc_info=True)

    try:
        yield
    finally:
        if stop_price_clock is not None:
            stop_price_clock()
        app.state.jobs.shutdown()
        from app.providers import codex_profile, resident
        try:
            try:
                codex_profile.shutdown()
            finally:
                resident.shutdown()
        finally:
            try:
                terminal.SESSION.close()
            finally:
                app.state.knowledge_clock.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    from app import backups
    from app.web.routers import backups as backup_routes

    settings = settings or Settings.from_env()
    backups.apply_pending(settings)
    app = FastAPI(
        title="Kriko", docs_url="/api/docs", redoc_url=None, lifespan=lifespan
    )
    app.state.settings = settings

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
        backup_routes.router,
        agenda.router,
        agent.router,
        agent_runtime.router,
        packs.router,
        prefs_router.router,
        query.router,
        research.router,
        subjects.router,
        analyze.router,
        appupdate.router,
        control.router,
        extension.router,
        factcheck.router,
        factcheck.verify_router,
        favicon.router,
        focus.router,
        health.router,
        history.router,
        jobs.router,
        keys.router,
        live.router,
        local_models.router,
        machine.router,
        bench.router,
        buyer.router,
        chat.router,
        cloud.router,
        compare.router,
        compareq.router,
        queue.router,
        products.router,
        marks.router,
        operations.router,
        prices.router,
        sites.router,
        terminal.router,
    ):
        app.include_router(router)

    # One runner per app, built here so a test app gets its own pool pointed at
    # its own temporary app.sqlite.
    # Idle, it hands the local model's memory back to the host: a finished run
    # must not hold video memory while Kriko sits in the background.
    try:
        app.state.jobs = JobRunner(app.state.settings, HANDLERS,
                                   on_idle=local_inference.release)
    except sqlite3.Error as error:
        # `JobRunner` opens the reader's `app.sqlite` for the job ledger, and
        # this is the first thing to touch it. An unopenable one — a home
        # directory that is read-only, a file another process holds, a corrupt
        # page — used to arrive as a bare `operationalerror: unable to open
        # database file`, which names neither the file nor the thing to do, and
        # it took the whole API down with it. Say both.
        raise RuntimeError(
            f"Kriko could not open its history file at "
            f"{app.state.settings.app_state_path}: {error}. Check that this "
            f"folder exists and is writable, then start Kriko again."
        ) from error
    # What the open answers watch to know the knowledge moved (B152.4).
    app.state.knowledge_clock = KnowledgeClock(app.state.settings.store_path)

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
            digest = request.headers.get(ext.DIGEST_HEADER, "")
            loaded = getattr(app.state, "extension_digests", {})
            # Bounded. The key is an Origin the caller chooses, and while a web
            # page cannot forge `chrome-extension://`, anything that can set a
            # header can fill this dict one unique origin at a time, for the
            # life of the process.
            if len(loaded) >= EXTENSION_SIGHTINGS_MAX and origin not in loaded:
                for stale in list(loaded)[: len(loaded) - EXTENSION_SIGHTINGS_MAX + 1]:
                    loaded.pop(stale, None)
            loaded[origin] = {
                "content_digest": digest if len(digest) == 64 and all(
                    char in "0123456789abcdef" for char in digest) else "",
                "version": request.headers.get(ext.VERSION_HEADER, ""),
            }
            app.state.extension_digests = loaded
            try:
                # In a worker thread: `state.connect` opens SQLite and
                # `record_extension` writes. Both are blocking calls, and this
                # middleware is `async` — so every extension request used to
                # stop the event loop for the length of a SQLite open and a
                # commit, which is exactly the loop every other request (and the
                # reader's own lookup) is waiting on.
                await run_in_threadpool(
                    _record_sighting,
                    app.state.settings.app_state_path, origin,
                    request.headers.get(ext.VERSION_HEADER, ""),
                )
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
        digest_name = "firefox_staged_digest" if origin.startswith("moz-extension://") else "extension_staged_digest"
        staged = getattr(app.state, digest_name, "")
        if staged:
            response.headers[ext.STAGED_HEADER] = staged
        response.headers["access-control-expose-headers"] = (
            f"{ext.MINIMUM_HEADER}, {ext.STAGED_HEADER}")
        return response

    # ── how much will be read ────────────────────────────────────────────
    #
    # Registered *before* `only_from_here` below, so that one stays outermost
    # (`add_middleware` inserts at the front, and `test_origins.py` asserts
    # that position). It still runs before any router, and therefore before
    # FastAPI hands a `bytes` body to `POST /api/packs/install`: that endpoint
    # used to buffer the whole request into memory and only then ask how big
    # it was, while the download path has had `MAX_PACK_BYTES` all along.
    #
    # `Content-Length` is the caller's own number, so this is a cheap refusal
    # rather than a guarantee: a chunked request declares nothing. The endpoint
    # checks the assembled length as well, which is where the guarantee lives.
    @app.middleware("http")
    async def not_too_large(request: Request, call_next):
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            log.warning("refused %s %s: %s bytes declared",
                        request.method, request.url.path, declared)
            return JSONResponse(
                {"detail": f"This request is larger than the "
                           f"{MAX_REQUEST_BYTES // (1024 * 1024)} MB limit."},
                status_code=413,
            )
        return await call_next(request)

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

    @app.get("/")
    def status():
        """Identify the native desktop/API sidecar without a browser UI."""
        return {
            "app": "Kriko",
            "desktop": "Tauri",
            "service": "local API",
            "health": "/api/health",
            "docs": "/api/docs",
        }

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
            # Three versions, never one. The binary updates through the shell, a
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
            "extension_port": app.state.settings.extension_port,
            # The extension's half of the handshake. It reads this on its own
            # schedule and compares its manifest against the floor, because
            # the app cannot make the browser do anything — only say what it
            # needs. /api/health rather than /api/extension: the extension
            # already polls this one, and a compatibility check that needs a
            # second request is a check that fails when the first one does.
            "minimum_extension_version": ext.MINIMUM_VERSION,
            "extension_version": _shipped_extension_version(),
            "port_is_ours": bool(app.state.settings.extension_port_bound),
            # ── E12: does it still *work* ────────────────────────────
            #
            # Everything above says what this process is, not whether it can
            # answer. `ok` was a constant `True`: a health check that cannot be
            # unhealthy. These two say what a reader (and the shell's own
            # watchdog) actually need — the store opens and holds what it should,
            # and the job runner is not saturated.
            "store_readable": _store_is_readable(app.state.settings.store_path),
            "jobs": _job_capacity(app.state.jobs),
        }

    return app


def main(argv=None) -> int:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="app.web")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=EXTENSION_PORT)
    parser.add_argument("--store", default=None)
    args = parser.parse_args(argv)

    # C3: this server has no accounts. Binding it anywhere but loopback hands
    # pack install/uninstall, agent configuration and the terminal endpoint to
    # the reader's whole network — and the module docstring above already says
    # "the default host is not a preference". A native client sends no Origin,
    # so the origin middleware would not object; only this check can.
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        if os.environ.get("KRIKO_ALLOW_LAN") != "1":
            parser.error(
                f"refusing --host {args.host!r}: this API has no authentication, "
                "so it answers on 127.0.0.1 only. Set KRIKO_ALLOW_LAN=1 if you "
                "really mean to publish it to your network."
            )
        print(
            f"warning: serving an unauthenticated API on {args.host}. Anyone who "
            "can reach this port can install packs and change agent settings.",
            file=sys.stderr,
        )

    overrides = {"store_path": Path(args.store)} if args.store else {}
    # `KRIKO_EXTENSION_BOUND` is what /api/health's `extension_port_bound`
    # reads (settings.py:150), and until now only src/app/sidecar.py set it —
    # a plain `python -m app.web` (this function) never did, so About and
    # Extension both asserted "something else took port 8787" on a server
    # that had simply never tried to bind it, because nobody had probed. Set
    # it honestly: this process holds EXTENSION_PORT exactly when it is the
    # port it was asked to serve on.
    selected_port = int(os.environ.get("KRIKO_EXTENSION_PORT", EXTENSION_PORT))
    os.environ["KRIKO_EXTENSION_BOUND"] = "1" if args.port == selected_port else "0"
    uvicorn.run(
        create_app(Settings.from_env(**overrides)),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
