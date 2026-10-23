"""The operations feed: what an agent is doing, live, whichever door it used.

An *operation* is one unit of agent-driven work on the knowledge
(`docs/AGENT_OPERATIONS.md`). `app/operations.py` records them; this serves
them.

**Why a poll and not a push.** The reader's own coding agent, in Kriko's
terminal or anywhere else, works through the MCP server — and that is the right
shape: the terminal is for the person, the app is for the operations. But a
call that takes forty seconds is invisible for forty seconds unless something
asks, and "is it doing anything?" is the question the app existed to answer
and could not.

``GET /api/operations` polls the table rather than being pushed to, exactly as
`routers/jobs.py` does and for the same reason: the MCP server is a *separate
process* writing to the same `app.sqlite`, so there is no in-process queue to
subscribe to and a queue would lose everything on reconnect anyway. The row is
the source of truth; the client reads it often. (The old SSE `/stream`
duplicate was retired; one feed, read by polling, is enough.)
"""

from fastapi import APIRouter, Depends, Query, Request

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["operations"])


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
    watch: str = Query(""),
    conn=Depends(get_app_state),
) -> dict:
    items = state.operations(
        conn, limit=limit, after_id=after_id, watching=_watched(watch)
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
