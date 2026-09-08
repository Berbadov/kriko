"""Reading the knowledge pipeline, live and afterwards.

Three endpoints, and the split between them is deliberate:

* `GET /api/pipeline/runs` — the history. What has been run, how it went, what
  it cost.
* `GET /api/pipeline/runs/{run_id}` — one run in full: its stages, its totals
  and its events. Cursored on `after`, so a client that has the first 300
  events asks for what came next rather than re-reading everything.
* `GET /api/pipeline/stream` — the same thing pushed, over SSE.

**Why SSE and not a WebSocket.** There is exactly one direction of traffic —
the server telling the window what happened — and SSE is that shape, with
reconnection handled by the browser and no protocol upgrade to get wrong
through a static-file mount. A WebSocket would be a second transport to keep
alive for no capability we need.

**And why the poll underneath it.** The emitter writes to `app.sqlite` from a
worker thread; this reads it from the event loop. A notification channel
between the two would mean sharing state across threads, which is precisely
the mistake that made every store-backed view fail in 0.3.1. Re-reading a
cursored index on a local SQLite file is a few hundred microseconds, and the
architecture stays: rows are the truth, the stream is a view of them.

The stream ends itself. A run that finished sends one last frame and closes,
rather than holding a request open forever against a run that will never
change again — and an idle stream with no run at all closes too, because the
window will open a new one when it needs it.
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.web import pipeline, state

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

#: How often the stream re-reads. Fast enough that a stage transition looks
#: immediate, slow enough to be free on a local file.
POLL_SECONDS = 0.5

#: A stream on a finished run closes after this. Not zero: the last events of
#: a run land in the same instant it is marked done, and a stream that closed
#: on the state change would drop them.
LINGER_SECONDS = 2.0

#: A stream with no run to watch is not an error, it is an idle window. It
#: closes so the connection is not held for the life of the process.
IDLE_SECONDS = 30.0


def _conn(request: Request):
    return state.connect(request.app.state.settings.app_state_path)


@router.get("/runs")
def list_runs(request: Request, limit: int = 30) -> dict:
    conn = _conn(request)
    try:
        return {
            "runs": pipeline.runs(conn, limit=limit),
            "stages": [
                {"stage": stage, "label": pipeline.STAGE_LABELS[stage]}
                for stage in pipeline.STAGES
            ],
        }
    finally:
        conn.close()


@router.get("/runs/{run_id}")
def read_run(run_id: str, request: Request, after: int = 0) -> dict:
    conn = _conn(request)
    try:
        run = pipeline.get_run(conn, run_id)
        if run is None:
            raise HTTPException(404, f"no pipeline run {run_id}")
        return _frame(conn, run, after)
    finally:
        conn.close()


def _frame(conn, run: dict, after: int) -> dict:
    events = pipeline.events(conn, run["run_id"], after=after)
    return {
        "run": run,
        "stages": pipeline.stages(conn, run["run_id"]),
        "events": events,
        # The cursor the client sends back next time. Carried in the frame
        # rather than computed client-side so the two cannot disagree about
        # what "already seen" means.
        "cursor": events[-1]["event_id"] if events else after,
        "live": run["state"] == "running",
    }


@router.get("/stream")
async def stream(request: Request, run_id: str | None = None, after: int = 0):
    async def frames():
        conn = _conn(request)
        cursor = after
        settled = 0.0
        idle = 0.0
        try:
            while True:
                if await request.is_disconnected():
                    return
                run = (
                    pipeline.get_run(conn, run_id)
                    if run_id
                    else pipeline.latest(conn)
                )
                if run is None:
                    idle += POLL_SECONDS
                    # A comment frame, not a data frame: it keeps the
                    # connection warm through a proxy without the client
                    # having to filter out empty payloads.
                    yield ": waiting for a run\n\n"
                    if idle >= IDLE_SECONDS:
                        return
                    await asyncio.sleep(POLL_SECONDS)
                    continue

                idle = 0.0
                frame = _frame(conn, run, cursor)
                cursor = frame["cursor"]
                yield f"data: {json.dumps(frame)}\n\n"

                if not frame["live"]:
                    settled += POLL_SECONDS
                    if settled >= LINGER_SECONDS:
                        return
                await asyncio.sleep(POLL_SECONDS)
        finally:
            conn.close()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            # Nothing between here and the window should buffer this. The
            # static mount and any proxy a reader has in front of the app both
            # default to holding a response until it is complete, which for a
            # stream means forever.
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
