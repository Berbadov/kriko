"""Bringing the window to the front, from outside the window.

The browser extension's "Open in Kriko" was a plain `<a href>` at the app's
own HTTP port. That opened the report *in the browser*, in a second tab, beside
the desktop app the reader already has running. The reader asked for the app and
got a web page that looks like it.

The fix cannot be a link, because a page has no way to raise a native window.
So the extension **posts a route**, and the shell does the raising:

* The **shell** (`kriko-gpui/src/engine.rs`) is already reading the
  sidecar's stdout for the port handshake, so it costs nothing to have the
  sidecar print one more line. `KRIKO_FOCUS` on stdout makes the shell call
  `show_window` — raise and focus. That is the only thing Rust does here, and
  it stays a supervisor rather than becoming a second engine.

The route is only printed, not kept: the window that used to poll it for the
navigation was the retired page, and nothing else reads it back.

**The route is validated, not trusted.** It arrives from a browser extension —
the one client that cannot be authenticated. A closed shape (a name, optionally
one `/`-separated id) keeps it unusable as an injection vector while staying
agnostic about which routes exist: this module must not hold the app's route
table any more than Rust holds the engine's.
"""

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["focus"])

#: The shell greps stdout for this. Must match `FOCUS_LINE` in
#: `kriko-gpui/src/engine.rs`; `test_focus.py` fails the suite if the two
#: drift, because a renamed constant here would silently stop raising the
#: window and look like a dead button.
#:
#: Deliberately does not contain `KRIKO_PORT` as a substring — the shell takes
#: the first stdout line that does as the port handshake.
FOCUS_LINE = "KRIKO_FOCUS"

#: A route name, optionally followed by one id segment: `knowledge`,
#: `result/9f2c...`. Anchored, bounded, and with no `#`, `?`, `:` or `//`, so
#: nothing a browser sends can become a different URL.
ROUTE = re.compile(r"^[a-z][a-z0-9-]{0,31}(/[A-Za-z0-9_-]{1,80})?$")


class FocusRequest(BaseModel):
    route: str = Field(min_length=1, max_length=128)


@router.post("/focus")
def ask_for_focus(body: FocusRequest, request: Request) -> dict:
    """Tell the shell to raise the window, and say whether anybody heard.

    `delivery` is the honest answer, and it replaced a `raised: true` that
    was structurally a lie. Whether a window was raised is not knowable from
    inside this process — but *whether anybody is reading our stdout* is,
    because the shell says so when it spawns us (`--supervised`). Those are
    different claims and the extension needs the second one:

      * `raised`   — a shell is attached; it read the line and called
                     `show_window`. The extension must not open a tab.
      * `no_shell` — nobody is reading stdout, because nobody is supervising
                     this process, so a browser tab is the *correct* answer
                     rather than a silent fallback the reader has to interpret.

    `raised` is kept as an alias because the extension ships on its own clock
    and an older one reads that key. It now says `delivery == "raised"`, which
    is the thing it always claimed to mean.
    """
    route = body.route.lstrip("#/")
    if not ROUTE.match(route):
        raise HTTPException(422, f"not a route this app could navigate to: {body.route!r}")

    # Unbuffered, like the port handshake: a frozen binary's buffered stdout
    # would hold this line until the process exited, i.e. forever.
    #
    # Printed either way. With no shell attached it costs one line in a log
    # nobody greps, and the alternative is a branch that makes the supervised
    # path the only one ever exercised.
    print(f"{FOCUS_LINE} {route}", flush=True)

    attached = bool(request.app.state.settings.shell_attached)
    delivery = "raised" if attached else "no_shell"
    return {
        "accepted": True,
        "route": route,
        "delivery": delivery,
        "raised": delivery == "raised",
    }
