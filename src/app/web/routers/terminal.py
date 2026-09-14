"""The terminal, over the transport that works on the reader's machine.

**This used to be a WebSocket, and that is the bug.** B107/B109 spent six
releases (0.7.4-0.7.11) on it. Each one closed a real path — a missing
`winpty-agent.exe`, a swallowed log, an unreported `start()` crash, an
unreported read failure, two rejections that closed before `accept()` — and
each time the reader reproduced and still saw a bare `[disconnected]`. The
0.7.10 banner finally returned the one fact worth having: close code **1006**,
"the opening handshake never finished", which the raw-socket probe in the same
entry proved was not the server's doing. The frozen sidecar answers a hand-made
`Upgrade: websocket` on the reader's own machine with `101` and real PTY bytes.
The webview does not get that far.

So the question stopped being "which path inside the handler is silent" and
became "why is this the only thing in the app on a transport nothing else
uses". Every other live view here — `/api/jobs/{id}/stream` — is Server-Sent
Events over ordinary HTTP with a polling fallback, and those demonstrably work
in the reader's install: it is how they watch a research job run. A WebSocket
needs an `Upgrade` handshake that an embedded webview, a proxy-aware network
stack, or an AV product can refuse *before any application code runs*, and 1006
is exactly the shape of that refusal.

A PTY does not need a duplex socket. It needs bytes out and bytes in, and those
are two ordinary HTTP endpoints:

* `GET /stream` — SSE, resumable from a byte offset. The session keeps its own
  transcript (`app/providers/termpty.py`), so this is a *view* of durable
  state, not the only chance to see it.
* `POST /input`, `POST /resize` — keystrokes and geometry.
* `GET /state` — the same fields as one SSE frame, for a client with no
  `EventSource` and for anything that wants a snapshot (the CLI, a TUI, a
  support question answered over a screenshot).

Three properties follow that the socket could not have:

1. **A transport failure now loses latency, not output.** The reader who
   reconnects sees what the shell printed while nobody was listening —
   including its dying words.
2. **Reporting a failure needs no live connection.** `failure` is a field, read
   by `GET /state`, not a frame someone had to be connected to receive.
3. **There is one live transport in this app instead of two.** The one that is
   proven to work here.

The two guards the socket handler did by hand are kept and made a dependency:
this endpoint is not reachable on the extension port, and not from an extension
origin, even though the global `only_from_here` middleware allows extensions
everywhere else. A shell is the one thing in this process that is worth more to
an attacker than the knowledge store.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.providers.termpty import SESSION
from app.web import origins
from app.web.settings import EXTENSION_PORT

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

logger = logging.getLogger(__name__)

#: How often `/stream` re-reads the transcript. A terminal is judged on feel,
#: and 60ms is below the threshold where typing reads as laggy; it is a
#: dictionary comparison against an integer offset, not a syscall.
POLL_SECONDS = 0.06

#: A comment frame this often, so an idle shell keeps the connection warm
#: through anything that times out a silent one.
HEARTBEAT_SECONDS = 15.0


def terminal_caller(request: Request) -> None:
    """Refuse anything that is not the desktop shell or a loopback page.

    A `Depends` rather than two lines at the top of each handler: three
    endpoints sharing one rule must not be able to drift apart, and the
    socket's version of this drifted twice.
    """
    server = request.scope.get("server")
    if server is not None and server[1] == EXTENSION_PORT:
        logger.warning("terminal refused: reached on the extension port")
        raise HTTPException(403, "This terminal cannot be reached on the extension port.")
    origin = request.headers.get("origin")
    if not origins.terminal_origin_is_allowed(origin):
        logger.warning("terminal refused: origin %r not allowed", origin)
        raise HTTPException(403, f"Origin {origin!r} is not allowed to open this terminal.")


guard = Depends(terminal_caller)


class Input(BaseModel):
    data: str = ""


class Size(BaseModel):
    cols: int = Field(default=80, ge=1, le=2000)
    rows: int = Field(default=24, ge=1, le=2000)


def _ensure(cols: int = 80, rows: int = 24) -> str:
    """Start the shell if it is not running; return the reason it would not.

    Returns rather than raises because every caller wants to answer *with* the
    reason — the reader is looking at the panel, and "could not start: ..." in
    it is the whole point of B109.

    A session that has *ended* is left ended. Respawning here would be a
    surprise rather than a kindness: the polling client asks for state twice a
    second, so a shell someone deliberately `exit`ed would come straight back,
    and the one signal saying it is gone would never survive long enough to be
    rendered. Starting a new one is `restart`, and it is a thing the reader
    asks for.
    """
    if SESSION.state()["ended"]:
        return ""
    try:
        SESSION.start(cols=cols, rows=rows)
    except Exception as exc:
        logger.exception("terminal session failed to start")
        return f"{type(exc).__name__}: {exc}"
    return ""


@router.get("/state", dependencies=[guard])
def terminal_state(offset: int = 0) -> dict:
    """Everything a client needs, in one request and with no stream at all.

    The fallback path when `EventSource` is missing, and the first thing to ask
    for in a bug report: it names the failure whether or not anyone was
    connected when it happened.
    """
    failure = _ensure()
    chunk, new_offset, dropped = SESSION.since(offset)
    state = SESSION.state()
    return {
        **state,
        "failure": state["failure"] or failure,
        "data": chunk,
        "offset": new_offset,
        "dropped": dropped,
    }


@router.post("/input", dependencies=[guard])
def terminal_input(body: Input) -> dict:
    failure = _ensure()
    if failure:
        raise HTTPException(503, failure)
    try:
        SESSION.write(body.data)
    except Exception as exc:
        logger.exception("terminal write failed")
        raise HTTPException(503, f"{type(exc).__name__}: {exc}") from exc
    return {"ok": True}


@router.post("/restart", dependencies=[guard])
def terminal_restart(body: Size) -> dict:
    """A new shell, and a clean transcript.

    `exit` is an ordinary thing to type, and before this the terminal had no
    way back from it for the life of the app. So is a shell that dies on its
    own, which is the state the 0.8.0 Windows install landed in permanently.
    """
    try:
        SESSION.restart(cols=body.cols, rows=body.rows)
    except Exception as exc:
        logger.exception("terminal session failed to restart")
        raise HTTPException(503, f"{type(exc).__name__}: {exc}") from exc
    return SESSION.state()


@router.post("/resize", dependencies=[guard])
def terminal_resize(body: Size) -> dict:
    failure = _ensure(cols=body.cols, rows=body.rows)
    if failure:
        raise HTTPException(503, failure)
    try:
        SESSION.resize(body.cols, body.rows)
    except Exception as exc:
        logger.exception("terminal resize failed")
        raise HTTPException(503, f"{type(exc).__name__}: {exc}") from exc
    return {"ok": True}


@router.get("/stream", dependencies=[guard])
async def terminal_stream(offset: int = 0, cols: int = 80, rows: int = 24):
    """Follow the transcript from `offset`.

    Every frame is the same JSON shape the client already knew from the socket
    (`{"type": "data" | "error", ...}`), so the panel's message handling did
    not have to be rewritten to lose the socket — only its transport.
    """
    failure = _ensure(cols=cols, rows=rows)

    async def events():
        cursor = offset
        if failure:
            yield f"data: {json.dumps({'type': 'error', 'message': failure})}\n\n"
            return
        idle = 0.0
        reported = ""
        while True:
            chunk, cursor, dropped = SESSION.since(cursor)
            if dropped:
                yield "data: " + json.dumps(
                    {
                        "type": "error",
                        "message": "Some output scrolled out of the buffer before it could be shown.",
                    }
                ) + "\n\n"
            if chunk:
                idle = 0.0
                yield f"data: {json.dumps({'type': 'data', 'data': chunk, 'offset': cursor})}\n\n"
            state = SESSION.state()
            if state["failure"] and state["failure"] != reported:
                reported = state["failure"]
                yield "data: " + json.dumps(
                    {"type": "error", "message": state["failure"]}
                ) + "\n\n"
            if state["ended"] and not chunk:
                yield "data: " + json.dumps({"type": "ended"}) + "\n\n"
                return
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                yield ": keepalive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
