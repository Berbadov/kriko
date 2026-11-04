"""Installed packs follow the index on their own (B166).

The Packs screen's Updates block was the only way a newer pack reached the
reader: nothing in the app pressed "Update all" for them, so knowledge that
"moves weekly" (CLAUDE.md, two update clocks) moved only when somebody
remembered to open a screen and check. With the block gone the clock has to
live here.

What it does, and does not:

- at startup, if the last successful automatic pass is older than a week,
  it submits a `pack_update` job. A job, never a call: the lifespan does not
  wait on a network fetch, so an unreachable index cannot delay opening;
- nothing installed is not a reason to ask. The installer carries no packs
  (#169), so a fresh install has an empty store and would otherwise fetch the
  index before the reader owns anything to update — a fetch that, because the
  pass may touch any pack, holds every other job behind it. An empty store
  starts the week instead, and the first pack the reader installs is already
  the version they chose;
- a pass that did not end well (no network, a download refused) is tried again
  at most once an hour, not at every launch. The attempt is remembered before
  the job is submitted, so a laptop opened on a train costs one failed fetch an
  hour rather than one per window — and the pass waiting on that fetch does not
  hold the job queue on every launch either;
- only packs that are *already installed* are touched (`installed_only`). A
  pack the reader uninstalled is not brought back by a clock;
- it goes through `pack_update`, hence `packstore.install`, hence the same
  refusal of a republished version as every other door;
- the week is counted from the last success, so a failed pass is not a week
  long silence: the retry clock above is the one that decides.

Nothing here decides anything from a network answer on the boot path: `due`
reads two rows, `submit_if_due` submits and returns.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.web import state
from kriko.store.db import connect as connect_store

log = logging.getLogger(__name__)

__all__ = [
    "ATTEMPTED_KEY",
    "CHECKED_KEY",
    "INTERVAL",
    "RETRY",
    "due",
    "record_success",
    "submit_if_due",
]

#: Key in `app.sqlite`'s `settings` table: when an automatic pass last ended
#: well (updated something, or found nothing newer).
CHECKED_KEY = "pack_updates_auto_checked_at"
#: When an automatic pass was last *started*, whatever came of it. A pass that
#: ends in failure records no success, and without this second stamp the next
#: launch would ask the release page again — on a machine with no network, on
#: every launch, with the fetch holding the job queue while it waits.
ATTEMPTED_KEY = "pack_updates_auto_attempted_at"
INTERVAL = timedelta(days=7)
#: How soon another attempt is allowed after one that did not end well. Short
#: enough that a reader who was offline is not a week behind, long enough that
#: opening the app twice in a minute asks GitHub once.
RETRY = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value) -> datetime | None:
    """One stored stamp, or None when it is absent, unreadable or naive.

    Naive counts as absent: everything written here is UTC, so a stamp without
    a zone is from somewhere else and comparing it would raise rather than
    answer.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def due(conn, now: datetime | None = None) -> bool:
    """Is an automatic pass allowed now?

    Two clocks, because a success and a failure mean different things: a week
    since the last success, and an hour since the last attempt. A stamp that
    cannot be read counts as absent, which asks — the safe direction.
    """
    now = now or _now()
    settings = state.all_settings(conn)
    last_success = _when(settings.get(CHECKED_KEY))
    if last_success is not None and now - last_success < INTERVAL:
        return False
    last_attempt = _when(settings.get(ATTEMPTED_KEY))
    return not (last_attempt is not None and now - last_attempt < RETRY)


def record_success(app_state_path, now: datetime | None = None) -> None:
    conn = state.connect(app_state_path)
    try:
        state.put_settings(conn, {CHECKED_KEY: (now or _now()).isoformat()})
    finally:
        conn.close()


def _has_installed_packs(settings) -> bool:
    """Could a pass update anything here?

    An absent store is an empty one: the installer carries no packs (#169), so
    a fresh install has no store at all and nothing for a clock to follow. A
    store that cannot be read is *assumed* to hold packs — skipping over an
    unreadable file would postpone every update by a week in silence, while the
    pass itself turns a broken store into a job failure the Activity screen
    shows.
    """
    path = Path(settings.store_path)
    if not path.exists():
        return False
    try:
        store = connect_store(path, read_only=True)
    except (sqlite3.Error, OSError):
        return True
    try:
        return store.execute("SELECT 1 FROM packs LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        return True
    finally:
        store.close()


def submit_if_due(settings, runner, now: datetime | None = None) -> str | None:
    """Submit the background update job when a week has passed; its id, or None."""
    now = now or _now()
    conn = state.connect(settings.app_state_path)
    try:
        if not due(conn, now):
            return None
        if not _has_installed_packs(settings):
            # Nothing to follow yet. The week starts, so a reader who has
            # installed no packs is not asked at every launch either.
            state.put_settings(conn, {CHECKED_KEY: now.isoformat()})
            return None
        # Remembered before the job exists, so a crash, a refused submission or
        # a fetch that never finishes all count as an attempt.
        state.put_settings(conn, {ATTEMPTED_KEY: now.isoformat()})
    finally:
        conn.close()
    job_id = runner.submit("pack_update", {"installed_only": True, "automatic": True})
    log.info("checking for pack updates in the background (job %s)", job_id)
    return job_id
