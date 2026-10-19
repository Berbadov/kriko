"""The engine's own clock for watched prices.

A watch is only worth having if it is read when the reader is not looking. The
extension asks on a timer too, but only while the browser is open, and the
desktop window may be closed to the tray with no browser at all. So the engine
asks itself: every `EVERY_MINUTES`, if a watched page is due, it submits the
`price_sweep` job that re-reads it (`pricewatch.sweep` decides which pages, and
re-reads one at most every few hours however often this ticks).

This is the stand-in for a service of Kriko's own that would do the same for a
phone as well as a desktop. The unit of work is already shaped for that move:
`pricewatch.sweep(conn, fetch)` takes the page fetcher as an argument and the
alerts are rows, so a hosted worker would call the same function and hand the
rows to a push channel instead of a toolbar badge. Until then this runs inside
the engine and only while the engine runs.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable

from app import cloud, pricewatch
from app.web import state

log = logging.getLogger(__name__)

EVERY_MINUTES = 30


def interval_seconds() -> float:
    try:
        minutes = float(os.environ.get("KRIKO_PRICE_SWEEP_MINUTES", EVERY_MINUTES))
    except ValueError:
        minutes = EVERY_MINUTES
    return max(1.0, minutes) * 60


class Sweeper:
    """Syncs with the relay, and submits a sweep when a watched page is due and the last one has finished."""

    def __init__(self, app_state_path, submit: Callable[[], str], *,
                 sync: Callable = cloud.sync_quietly):
        self.path = app_state_path
        self.submit = submit
        self.sync = sync
        self.job_id = ""

    def tick(self) -> str:
        """The id of the job submitted, or "" when nothing was due or one is still running."""
        conn = state.connect(self.path)
        try:
            # A reader with a relay hears from it on the same clock: what it
            # watched while this computer was off, and what was changed on the
            # phone. A relay that does not answer is not a reason to skip the rest.
            self.sync(conn)
            if self.job_id:
                job = state.get_job(conn, self.job_id)
                if job and not job["done"]:
                    return ""
            if not pricewatch.due(conn):
                return ""
        finally:
            conn.close()
        self.job_id = self.submit()
        return self.job_id


def start(sweeper: Sweeper, *, every: float | None = None) -> Callable[[], None]:
    """Run the clock on a daemon thread. Returns the function that stops it."""
    stop = threading.Event()
    wait = every if every is not None else interval_seconds()

    def loop() -> None:
        while not stop.wait(wait):
            try:
                sweeper.tick()
            except Exception:  # noqa: BLE001 - a failed tick must not end the clock
                log.warning("the watched-page clock could not tick", exc_info=True)

    threading.Thread(target=loop, name="price-clock", daemon=True).start()
    return stop.set
