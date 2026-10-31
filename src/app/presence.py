"""An optional, anonymous daily ping, so the project can count active installs.

Kriko has no account and no analytics, and this module does not change that.
The reader opts in on the Usage settings page, and only then does the app send
one request per day to a configured endpoint carrying exactly two facts: a
random install id and the app version. No question, no product, no page, no
URL, no key, no timestamp finer than the day — the id exists only to be
counted as distinct.

**Off by default.** `enabled()` reads the `presence_enabled` setting and is
empty ("off") unless the reader set it to "1", so an installation that never
opens the screen never sends anything. When off, `maybe_ping` is a no-op and
the app's only outbound requests remain the ones the reader already knows:
the update check and the pack index.

**Fail quiet**, like the update check (`app/appupdate.py`): a reader offline,
behind a proxy, or with no endpoint configured gets nothing, and the ping
never delays or breaks a startup. The ping runs on a daemon thread so the
lifespan never blocks on it.

**One per day.** The last ping day is stored in the app-state settings; the
id is stored beside it so it is generated once and stable per install.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from datetime import date
from urllib.parse import urlparse

from app import prefs

log = logging.getLogger(__name__)

#: The reader's choice, stored as "1"/"" like every other string setting.
PRESENCE_ENABLED = prefs.PRESENCE_ENABLED
#: Where the daily ping goes when the reader opted in. Empty means off even
#: when enabled, so a fork that never configures an endpoint sends nothing.
#: Overridable in `Settings`, like the release API URL.
DEFAULT_ENDPOINT = ""

API_TIMEOUT = 10
USER_AGENT = "kriko-presence"

#: Settings keys this module owns, stored in the app-state store.
_ID_KEY = "presence_install_id"
_DAY_KEY = "presence_last_day"


def _open(url: str, body: bytes, timeout: int):
    if urlparse(url).scheme != "https":
        raise ValueError(f"refusing a non-https presence URL: {url!r}")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — scheme checked


def install_id(conn) -> str:
    """This install's random id, generated once and kept in the local store.

    Never leaves the machine except in the opted-in ping, and never identifies
    anything but the count.
    """
    from app.web import state

    stored = state.all_settings(conn).get(_ID_KEY, "")
    if stored:
        return stored
    import uuid

    fresh = uuid.uuid4().hex
    state.put_settings(conn, {_ID_KEY: fresh})
    return fresh


def enabled(conn) -> bool:
    """The reader opted in. Unset, empty or anything but "1" is off."""
    return prefs.read(conn).get(PRESENCE_ENABLED) == "1"


def _last_day(conn) -> str:
    from app.web import state

    return str(state.all_settings(conn).get(_DAY_KEY, "")).strip()


def maybe_ping(settings, app_state_path, version: str, *, endpoint: str | None = None) -> bool:
    """Send the daily ping if the reader opted in and today's was not sent.

    Returns whether a ping was sent. Never raises: a failed ping is logged
    and forgotten, exactly like a failed update check.
    """
    from app.web import state

    url = (endpoint if endpoint is not None else settings.presence_endpoint).strip()
    if not url:
        return False
    conn = state.connect(app_state_path)
    try:
        if not enabled(conn):
            return False
        today = date.today().isoformat()
        if _last_day(conn) == today:
            return False
        ident = install_id(conn)
    finally:
        conn.close()
    body = json.dumps({"id": ident, "version": version}).encode()
    try:
        _open(url, body, API_TIMEOUT)
    except Exception as cause:  # noqa: BLE001 — a ping is never a failure the reader sees
        log.info("presence ping failed: %s", cause)
        return False
    conn = state.connect(app_state_path)
    try:
        state.put_settings(conn, {_DAY_KEY: today})
    finally:
        conn.close()
    return True


def ping_in_background(settings, app_state_path, version: str) -> None:
    """Run `maybe_ping` off the caller's thread, so startup never waits on it."""
    if os_environ_no_presence():
        return
    threading.Thread(
        target=maybe_ping,
        args=(settings, app_state_path, version),
        name="presence-ping",
        daemon=True,
    ).start()


def os_environ_no_presence() -> bool:
    import os

    return bool(os.environ.get("KRIKO_NO_PRESENCE"))


def status(conn, endpoint: str) -> dict:
    """What the Usage settings page shows: on or off, and where it would go."""
    return {
        "enabled": enabled(conn),
        "endpoint": endpoint,
        "last_day": _last_day(conn),
    }
