# The local protocol

Kriko's engine is one local HTTP server (FastAPI, `src/app/web/app.py`). Every route sits under `/api`, and the server listens on loopback only. Three clients speak to it. This page says how each finds the engine and how each talks to it. The routes themselves are listed in `docs/INTERNALS.md`.

## The three clients

- **The browser extension.** Only `extension/background.js` calls the engine. The content script and the hover panel message the background worker, which makes every request through `_getApp` and `_postApp`. Each request carries the extension's version.
- **The desktop app.** `kriko-gpui/src/api.rs` speaks HTTP/1.0 over a plain socket, through `get`, `post`, `put`, `delete` and `request`. Screens reach it only through the background executor, never directly.
- **The terminal interface.** `src/app/tui/client.py` uses the standard library's `urllib`, with a 30 second timeout.

## Ports

- **8787 is fixed.** `EXTENSION_PORT` in `src/app/web/settings.py` is the one port that anything outside the process may assume. The extension's default base is `http://127.0.0.1:8787`, and a reader can change it in the extension's storage (`krikoApiBaseUrl`). `python -m app.web` also listens there.
- **The sidecar's port is announced.** `src/app/sidecar.py` binds port 0, so the operating system picks a free port, and its first stdout line is `KRIKO_PORT <n>`. If 8787 is also free, it binds that too and prints `KRIKO_EXTENSION_PORT <n>`. A second Kriko on the same machine simply leaves 8787 to the first.
- **The desktop app finds an engine in this order** (`kriko-gpui/src/engine.rs`): `KRIKO_URL` if set; the sidecar beside the app; an engine already answering on 8787, which it attaches to; a source checkout's `python -m app.sidecar`.
- **The terminal interface** tries `--url`, then `KRIKO_URL`, then 8787 (`src/app/tui/client.py`).

## The health handshake

`GET /api/health` answers `{"ok": true, "version": ..., "schema_version": ..., ...}`. The desktop app polls it after reading the port line and shows its starting screen until `ok` is true. If the engine never answers, the screen shows the sidecar's stderr, not a blank window. The extension calls the same route to decide whether to show Kriko as connected, and reads `version` from the same answer.

Every answer also carries two headers the extension reads. `X-Kriko-Minimum-Extension` is the oldest extension this app accepts. `X-Kriko-Staged-Digest` identifies the extension build the app carries, so a browser copy that is out of date reloads itself.

## Jobs

Long work is a row, not a request. A `POST` that starts work returns at once with `{"job_id": ..., "kind": ...}`. Examples are `/api/research`, `/api/packs/build`, `/api/packs/update` and `/api/agents/{agent_id}/install`. The client then polls `GET /api/jobs/{job_id}`.

A job is in one of six states: `queued`, `running`, `succeeded`, `failed`, `cancelled` or `interrupted`. The last four are terminal. A job waits while a running job claims the same pack, and the reader's setting decides how many run at once (`src/app/web/jobs.py`). Rows live in `app.sqlite` (`src/app/web/state.py`), so a result outlives the request and the process. A job that was running when the process died is marked `interrupted` at the next startup (`JobRunner.recover`).

The controls are `POST /api/jobs/{job_id}/cancel`, which asks the job to stop at its next checkpoint; `POST /api/jobs/{job_id}/say`, which hands it a note; and `POST /api/jobs/{job_id}/retry`, which starts a new job from a finished one. Retry answers `409` while the job is still running.

## Errors

Errors use FastAPI's shape: the HTTP status, and a JSON body with `detail`.

- A request from an origin that is not allowed is `403`, with `detail` saying why.
- A body the engine cannot read is `422`, with `detail` as a list of `{loc, msg, type}`.
- An unhandled exception is `500`, with `detail` as `"ExceptionType: message"` and `where` as the request path. The traceback goes to the log.

Each client reads that shape. The extension throws `Kriko refused that (<detail>)`. `api.rs` flattens a string, a list or an object with `message` or `error` into one line. The terminal interface raises `EngineError` with the status. A status of `0` means no answer at all, which is the ordinary state when the engine is not running.

## Agreement

`src/app/tests/test_the_clients_call_routes_that_exist.py` enforces that every path a client calls is a route the engine serves, and that the verb agrees wherever the source names one. It reads the calls from the JavaScript, Rust and Python sources, and the routes from the engine's OpenAPI schema. A new call or a new route is covered without editing the test. A route that no client calls is reported as a warning rather than a failure, because the MCP server and the command line use some of them. The port and handshake tests check the constants above.
