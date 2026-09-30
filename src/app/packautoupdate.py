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
- only packs that are *already installed* are touched (`installed_only`). A
  pack the reader uninstalled is not brought back by a clock;
- it goes through `pack_update`, hence `packstore.install`, hence the same
  refusal of a republished version as every other door;
- the week is counted from the last success, so an offline launch is asked
  again at the next one rather than a week later.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.web import state

log = logging.getLogger(__name__)

__all__ = ["CHECKED_KEY", "INTERVAL", "due", "record_success", "submit_if_due"]

#: Key in `app.sqlite`'s `settings` table: when an automatic pass last ended
#: well (updated something, or found nothing newer).
CHECKED_KEY = "pack_updates_auto_checked_at"
INTERVAL = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def due(conn, now: datetime | None = None) -> bool:
    stamp = state.all_settings(conn).get(CHECKED_KEY)
    if not isinstance(stamp, str) or not stamp:
        return True
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    return (now or _now()) - last >= INTERVAL


def record_success(app_state_path, now: datetime | None = None) -> None:
    conn = state.connect(app_state_path)
    try:
        state.put_settings(conn, {CHECKED_KEY: (now or _now()).isoformat()})
    finally:
        conn.close()


def submit_if_due(settings, runner, now: datetime | None = None) -> str | None:
    """Submit the background update job when a week has passed; its id, or None."""
    conn = state.connect(settings.app_state_path)
    try:
        if not due(conn, now):
            return None
    finally:
        conn.close()
    job_id = runner.submit("pack_update", {"installed_only": True, "automatic": True})
    log.info("checking for pack updates in the background (job %s)", job_id)
    return job_id
