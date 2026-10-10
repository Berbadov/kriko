"""The operations feed: what an agent is doing, live, whichever door it used.

An *operation* is one unit of agent-driven work on the knowledge
(`docs/AGENT_OPERATIONS.md`). `app/operations.py` records them; this serves
them.

**Why a stream and not a list.** The reader's own coding agent, in Kriko's
terminal or anywhere else, works through the MCP server — and that is the right
shape: the terminal is for the person, the app is for the operations. But a
call that takes forty seconds is invisible for forty seconds unless something
pushes, and "is it doing anything?" is the question the app existed to answer
and could not.

`/stream` polls the table rather than being pushed to, exactly as
`routers/jobs.py` does and for the same reason: the MCP server is a *separate
process* writing to the same `app.sqlite`, so there is no in-process queue to
subscribe to and a queue would lose everything on reconnect anyway. The row is
the source of truth; the stream is a way of reading it often.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.web import state
from app.web.deps import get_app_state, get_jobs

router = APIRouter(prefix="/api", tags=["operations"])

#: How often `/stream` looks for new rows. A tool call is a human-scale event —
#: half a second is live to a reader and costs one indexed query.
POLL_SECONDS = 0.5

#: How long a connection lives before the client is asked to reconnect. A
#: browser tab left open for a week must not hold a connection for a week.
MAX_SECONDS = 3600


def _watched(watch: str) -> list[int]:
    """The ids a caller says it is still watching, from one query parameter.

    Comma-separated rather than repeated, because this rides on every poll and
    a URL is the cheapest place to put a handful of integers. Anything that is
    not a number is dropped rather than refused: a stale or truncated list must
    degrade into a slightly staler feed, never into a 422 that stops the feed
    altogether.
    """
    out: list[int] = []
    for piece in (watch or "").split(","):
        piece = piece.strip()
        if piece.isdigit():
            out.append(int(piece))
    return out[: state.MAX_WATCHED]


@router.get("/operations")
def list_operations(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    after_id: int = Query(0, ge=0),
    before_id: int = Query(0, ge=0),
    watch: str = Query(""),
    conn=Depends(get_app_state),
) -> dict:
    items = state.operations(
        conn, limit=limit, after_id=after_id, before_id=before_id,
        watching=_watched(watch)
    )
    return {
        "items": items,
        "running": state.running_operations(conn),
        # The knowledge clock (B152.4), carried on the feed the extension's
        # panel already polls, so "a card was added" costs it no second
        # request.
        "knowledge": request.app.state.knowledge_clock.now(),
        # The newest id the caller has now seen, so a poller that missed the
        # stream can carry on from a number rather than from a timestamp.
        # Only *new* rows may move it: a re-read row is one the caller already
        # holds, and letting it push the cursor forward would be harmless today
        # and wrong the first time the two ever disagree.
        "last_id": max(
            (one["op_id"] for one in items if one["op_id"] > after_id),
            default=after_id,
        ),
    }


@router.get("/operations/stream")
async def stream_operations(
    after_id: int = Query(0, ge=0),
    # The runner carries the settings, which is how `routers/jobs.py` reaches
    # `app_state_path` for its own stream. Same door, so there is one way to
    # open a connection that outlives a request rather than two.
    request_jobs=Depends(get_jobs),
) -> StreamingResponse:
    """Server-Sent Events: one `data:` line per operation, oldest first.

    Its own connection rather than the request-scoped one: this outlives the
    handler, and a connection handed over by a dependency is closed when the
    request that opened it is considered done.
    """

    async def events():
        conn = state.connect(request_jobs.settings.app_state_path)
        cursor = after_id
        # Every row this connection has sent that was `running` when it went,
        # against what it looked like when it went. The stream owns this rather
        # than the client, because a client listening over SSE has no way to
        # ask for anything — and because a reconnect starts a fresh set, which
        # is correct: the new connection re-reads from its own cursor and
        # learns the same rows again.
        watching: dict[int, str] = {}
        try:
            waited = 0.0
            while waited < MAX_SECONDS:
                rows = state.operations(
                    conn, limit=200, after_id=cursor, watching=sorted(watching)
                )
                sent = False
                for row in rows:
                    op_id = row["op_id"]
                    body = json.dumps(row, default=str)
                    if op_id > cursor:
                        cursor = op_id
                    elif watching.get(op_id) in (None, body):
                        # Either not ours to re-send, or unchanged since we
                        # last did. A row re-sent every half second because it
                        # is merely still running would turn a live feed into a
                        # busy one, which is a different kind of unreadable.
                        continue
                    if row["state"] == "running":
                        watching[op_id] = body
                    else:
                        # It has an ending now — the thing this stream existed
                        # to deliver and never did. Send it once more, then
                        # stop watching it.
                        watching.pop(op_id, None)
                    sent = True
                    yield f"data: {body}\n\n"
                if not sent:
                    # A comment frame, so a proxy between here and the browser
                    # does not decide an idle stream is a dead one.
                    yield ": waiting\n\n"
                await asyncio.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
        finally:
            conn.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
