"""Bringing the window to the front, from outside the window.

The browser extension's "Open in Kriko" was a plain `<a href>` at the app's
own HTTP port. That works — the SPA is served over HTTP and the route resolves
— but it opens the report *in the browser*, in a second tab, beside the desktop
app the reader already has running. The reader asked for the app and got a
web page that looks like it.

The fix cannot be a link, because a page has no way to raise a native window.
So the handoff goes the other way: the extension **posts a route**, and the
two processes that can act on it each pick up their half.

* The **shell** (`tauri/src-tauri/src/main.rs`) is already reading the
  sidecar's stdout for the port handshake, so it costs nothing to have the
  sidecar print one more line. `KRIKO_FOCUS` on stdout makes the shell call
  `show_window` — raise and focus. That is the only thing Rust does here, and
  it stays a supervisor rather than becoming a second engine.
* The **window** polls `GET /api/focus` and navigates. It has to be a poll from
  the page rather than a push into it: the shell can raise a window but has no
  business knowing the SPA's route table, and the SPA cannot be reached from
  another process except through this server.

**A pending focus is deliberately in memory, and deliberately expires.** It is
not history — it is a nudge between two live processes, and `app.sqlite` is for
things that must outlive the process. A route persisted across a restart would
surface as the window jumping to a stale report days later, which is worse than
losing the nudge. One server process serves both sockets, so in-memory is also
simply *correct* here: the extension's POST and the window's GET are handled by
the same object.

**The route is validated, not trusted.** It arrives from a browser extension —
the one client that cannot be authenticated — and it ends up in the SPA's
`location.hash`. A closed shape (a name, optionally one `/`-separated id) is
enough to make it unusable as an injection vector while staying agnostic about
which routes exist: this module must not hold the app's route table any more
than Rust holds the engine's.

Consume-once on read: a nudge acted on is spent. Two windows would otherwise
both navigate, and a window reopened later would replay an old jump.
"""

import re
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["focus"])

#: The shell greps stdout for this. Must match `FOCUS_LINE` in
#: `tauri/src-tauri/src/main.rs`; `test_sidecar.py` fails the suite if the two
#: drift, because a renamed constant here would silently stop raising the
#: window and look like a dead button.
#:
#: Deliberately does not contain `KRIKO_PORT` as a substring — the shell takes
#: the first stdout line that does as the port handshake.
FOCUS_LINE = "KRIKO_FOCUS"

#: How long a nudge is worth acting on. Long enough for a cold window to
#: finish booting and poll once; short enough that a window opened by hand
#: minutes later does not jump somewhere the reader has forgotten asking for.
TTL_SECONDS = 30.0

#: A route name, optionally followed by one id segment: `knowledge`,
#: `result/9f2c...`. Anchored, bounded, and with no `#`, `?`, `:` or `//`, so
#: what the SPA puts in its hash cannot become a different URL.
ROUTE = re.compile(r"^[a-z][a-z0-9-]{0,31}(/[A-Za-z0-9_-]{1,80})?$")


class FocusRequest(BaseModel):
    route: str = Field(min_length=1, max_length=128)


def _pending(request: Request) -> dict | None:
    return getattr(request.app.state, "focus", None)


@router.post("/focus")
def ask_for_focus(body: FocusRequest, request: Request) -> dict:
    """Record a route and tell the shell to raise the window.

    Returns `raised` as a claim about what was *attempted*, never about what
    happened: whether a shell is listening on the other end of this stdout is
    not knowable from here, and pretending otherwise would make the extension
    hide its own fallback.
    """
    route = body.route.lstrip("#/")
    if not ROUTE.match(route):
        raise HTTPException(422, f"not a route this app could navigate to: {body.route!r}")

    request.app.state.focus = {"route": route, "at": time.monotonic()}
    # Unbuffered, like the port handshake: a frozen binary's buffered stdout
    # would hold this line until the process exited, i.e. forever.
    print(f"{FOCUS_LINE} {route}", flush=True)
    return {"accepted": True, "route": route, "raised": True}


@router.get("/focus")
def take_focus(request: Request) -> dict:
    """The route the window should jump to, once.

    Cleared on read even when it has expired, so a stale entry cannot sit in
    memory being re-checked for the life of the process.
    """
    pending = _pending(request)
    request.app.state.focus = None
    if pending is None:
        return {"route": None}
    if time.monotonic() - pending["at"] > TTL_SECONDS:
        return {"route": None, "expired": True}
    return {"route": pending["route"]}

