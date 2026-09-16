"""The unattended loop: the agenda, walked without anybody pressing anything.

G5 says Kriko runs unattended. Until B98 it ran when watched — `app/agenda.py`
worked out what was worth researching next, `tasks.agenda_run` walked it, and
every walk was a button press. This is the timer that presses it.

It is sequenced deliberately *after* B92 (a plane that can actually read), for
the reason the backlog row gives: a scheduler driving a plane that gathers
nothing would fill the runs table with successful nothing, which is worse than
no scheduler because it looks like it is working.

Four decisions, and each one is about what the loop refuses to do.

**Off until the reader turns it on.** An installation that started spawning
agents or spending money because it was left open would be a defect no matter
how good the agenda was. `enabled` defaults to False and lives in the
reader's own `app.sqlite` settings, so a restart does not re-consent for them.

**It will not schedule a plane that cannot read.** The `agent` plane's whole
output is a brief for a human to hand over; nobody is there to hand it over,
so an unattended `agent` run produces a brief that is never read and a run row
that says it succeeded. The tick refuses it by name, and refuses `harness`
with no CLI and `api` with no key the same way — the refusal is recorded as a
sentence, because a loop that silently declines is indistinguishable from a
loop that is broken.

**One thing at a time.** The job runner has a single worker (see
`app/web/jobs.py`), so a tick that submitted while work was in flight would
queue behind it rather than run beside it. Two ticks of a slow schedule would
then be a backlog. It asks `state.work_in_flight` first and skips.

**No stampede after a week off.** The next due time is computed from the
*stored* timestamp of the last run, so a machine that was closed for seven
days runs once when it opens, not seven times. And the first tick after
startup waits out `STARTUP_GRACE_SECONDS`: opening the app must not be the
same event as starting a run.

The decision and the thread are separate on purpose. `decide()` is a pure
function of (now, settings, readiness, in-flight count) and every rule above
is tested through it without a timer; `Scheduler` is the thin part that sleeps
and calls it. A loop whose rules can only be tested by waiting is a loop whose
rules do not get tested.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.web import state

log = logging.getLogger(__name__)

#: The settings key the whole feature lives under. One JSON blob rather than
#: five keys, so reading "is this on and how" is one row and one shape.
KEY = "schedule"

#: How long after startup the first tick may fire. Opening the app is not a
#: request to start a run, and a reader who opens it to change the setting
#: should get there before the loop acts on the old one.
STARTUP_GRACE_SECONDS = 120.0

#: How often the thread wakes to *ask*. Unrelated to how often it runs, which
#: is `every_hours`: a short poll is what makes a setting change take effect
#: without a restart.
POLL_SECONDS = 60.0

#: A floor under the reader's interval. Not a policy about cost — a floor
#: under a mistake: `every_hours = 0` in a settings file must not become a
#: loop that submits as fast as the worker drains.
MIN_HOURS = 0.25

DEFAULTS = {
    "enabled": False,
    "every_hours": 24.0,
    "rows": 5,
    # `harness` rather than `agent`, and this is the one place in the codebase
    # where the unattended default is *not* the do-nothing plane: the whole
    # point of the loop is that nobody is watching, and the agent plane needs
    # somebody watching. It still will not run without a CLI installed.
    "plane": "harness",
    "budget_usd": 0.0,
    "max_documents": 5,
}

#: What a plane needs before an unattended tick will use it. The key is the
#: plane; the value is the sentence the reader gets when it is missing.
NEEDS = {
    "agent": (
        "the agent plane only writes a brief for someone to hand to an agent, "
        "and nobody is here to hand it over — choose the harness plane, which "
        "runs your agent for you"
    ),
    "harness": (
        "no coding-agent command-line tool was found on PATH, so there is "
        "nothing to start"
    ),
    "api": "no research keys are set, so the paid plane cannot run",
}


@dataclass(frozen=True)
class Decision:
    """Whether this tick runs, and the sentence explaining it either way.

    `reason` is filled on both paths. A skipped tick with no reason is the
    failure this class exists to prevent: the reader cannot tell a loop that
    decided not to run from a loop that is not running.
    """

    run: bool
    reason: str
    due_at: str = ""


def settings_for(conn) -> dict:
    """The schedule as stored, merged over the defaults.

    Merged rather than replaced, so a settings blob written by an older
    version — or by a reader editing one field — still answers every question
    this module asks of it.
    """
    stored = state.all_settings(conn).get(KEY)
    merged: dict[str, object] = dict(DEFAULTS)
    if isinstance(stored, dict):
        merged.update({k: v for k, v in stored.items() if k in DEFAULTS})
    hours = merged["every_hours"] or 0
    rows = merged["rows"] or 1
    merged["every_hours"] = max(
        MIN_HOURS, float(hours) if isinstance(hours, (int, float, str)) else MIN_HOURS
    )
    merged["rows"] = max(
        1, min(100, int(rows) if isinstance(rows, (int, float, str)) else 1)
    )
    merged["enabled"] = bool(merged["enabled"])
    merged["plane"] = str(merged["plane"] or "harness")
    return merged


def status(conn) -> dict:
    """What the screen shows: the setting, plus what the loop last did.

    The history half is kept under its own key so that saving the setting
    cannot overwrite the record of what happened, and so that the record
    survives the reader turning the loop off — "it ran four times and the last
    one kept nothing" is exactly what they want after switching it off.
    """
    history = state.all_settings(conn).get(f"{KEY}_last")
    return {
        **settings_for(conn),
        "last": history if isinstance(history, dict) else {},
        "in_flight": state.work_in_flight(conn),
    }


def _parse(when: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(when))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def decide(
    now: datetime,
    schedule: dict,
    *,
    last_run_at: str = "",
    ready: bool = True,
    in_flight: int = 0,
    started_at: datetime | None = None,
) -> Decision:
    """Should this tick submit a run, and why not if not.

    Pure, and every rule in the module docstring is asserted through this
    rather than through a thread. The order is the order of increasing cost to
    get wrong: consent first, then whether the plane could do anything, then
    whether it would pile up, and only then the clock.
    """
    if not schedule.get("enabled"):
        return Decision(False, "the unattended loop is off")

    plane = schedule.get("plane") or "harness"
    if plane in NEEDS and not ready:
        return Decision(False, NEEDS[plane])
    if plane not in NEEDS:
        return Decision(False, f"no such research plane: {plane}")

    if in_flight:
        return Decision(
            False, f"{in_flight} job(s) already queued or running — skipping this turn"
        )

    if started_at is not None:
        grace = started_at + timedelta(seconds=STARTUP_GRACE_SECONDS)
        if now < grace:
            return Decision(
                False,
                "just started — the first unattended run waits a couple of minutes",
                grace.isoformat(timespec="seconds"),
            )

    every = timedelta(hours=max(MIN_HOURS, float(schedule.get("every_hours") or 0)))
    previous = _parse(last_run_at)
    if previous is not None:
        due = previous + every
        if now < due:
            # Computed from the stored timestamp rather than counted in memory,
            # which is what stops a machine that was off for a week from
            # running seven times when it opens.
            return Decision(
                False, "not due yet", due.isoformat(timespec="seconds")
            )
    return Decision(True, f"due — walking {schedule['rows']} row(s) of the agenda")


class Scheduler:
    """The thread. It sleeps, asks `decide`, and submits when told to.

    A daemon thread rather than an async task: the tick's work is a `submit`
    into the existing job runner and two short SQLite reads, and putting it on
    the event loop would mean a blocking read in the same loop that serves the
    reader's requests.

    Stopping is cooperative and immediate — `stop()` sets an event the sleep
    waits on, so shutdown does not wait out a poll interval.
    """

    def __init__(self, settings, runner):
        self._settings = settings
        self._runner = runner
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: datetime | None = None
        #: Counted for the tests and for the status line. A loop that claims
        #: to be running is worth less than one that says when it last looked.
        self.ticks = 0

    # ── the loop ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._started_at = datetime.now(UTC)
        self._thread = threading.Thread(
            target=self._loop, name="kriko-schedule", daemon=True
        )
        self._thread.start()

    def stop(self, wait: float = 0.0) -> None:
        self._stop.set()
        if self._thread is not None and wait:
            self._thread.join(timeout=wait)

    def _loop(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                # A tick that raised must not end the loop. The next one may
                # well succeed, and a scheduler that dies on one bad read is a
                # feature that silently stops working weeks later.
                log.warning("unattended tick failed", exc_info=True)

    # ── one tick ─────────────────────────────────────────────────────────

    def tick(self, now: datetime | None = None, *, from_timer: bool = True) -> Decision:
        """Ask, record the answer, and submit if the answer was yes.

        Returns the decision so a test — and the route that offers a manual
        "check now" — gets the same sentence the reader sees.

        `from_timer=False` waives only the startup grace. The grace exists so
        that *opening the app* is not the same event as starting a run;
        somebody pressing "check now" is present and asking, and telling them
        to wait two minutes would be answering a question they did not ask.
        Everything else still applies — a manual check is a check, not a way
        to run ahead of the schedule.
        """
        now = now or datetime.now(UTC)
        conn = state.connect(self._settings.app_state_path)
        try:
            schedule = settings_for(conn)
            history = state.all_settings(conn).get(f"{KEY}_last") or {}
            decision = decide(
                now,
                schedule,
                last_run_at=str(history.get("run_at") or ""),
                ready=self._ready(schedule.get("plane") or ""),
                in_flight=state.work_in_flight(conn),
                started_at=self._started_at if from_timer else None,
            )
            self.ticks += 1
            record = {
                **(history if isinstance(history, dict) else {}),
                "checked_at": now.isoformat(timespec="seconds"),
                "reason": decision.reason,
                "due_at": decision.due_at,
            }
            if decision.run:
                job_id = self._runner.submit(
                    "agenda_run",
                    {
                        "rows": schedule["rows"],
                        "backend": schedule["plane"],
                        "budget_usd": schedule["budget_usd"],
                        "max_documents": schedule["max_documents"],
                    },
                )
                # Written *after* the submit, so a crash between the two
                # leaves the run un-recorded rather than recorded as done —
                # a duplicated run is recoverable and a skipped one is
                # invisible.
                record["run_at"] = now.isoformat(timespec="seconds")
                record["job_id"] = job_id
                record["runs"] = int(record.get("runs") or 0) + 1
            state.put_settings(conn, {f"{KEY}_last": record})
            return decision
        finally:
            conn.close()

    def _ready(self, plane: str) -> bool:
        """Whether that plane could do anything right now.

        Imported here rather than at module scope because both answers are
        environment reads — an executable on PATH, a key in a file — and the
        answer at import time is not the answer at tick time.
        """
        if plane == "harness":
            from app.providers import harness

            return bool(harness.available())
        if plane == "api":
            from app import keys

            return bool(keys.ready())
        # The agent plane is never ready for an unattended run, by definition:
        # its output is a brief for a person who is not here.
        return False
