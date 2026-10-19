"""What the knowledge pipeline is doing, while it does it.

A `jobs` row says whether long work is running, how far along it claims to be
and what it printed. It cannot say what the *pipeline* did — and those are
different questions. A research run that gathered nothing and a run that
gathered plenty and lost all of it at the grounding check produce
near-identical job logs, and they are completely different situations: the
first is a discovery problem, the second is an evidence problem. The reader
had no way to tell them apart, so "the terminal is not functioning" was a fair
description of a terminal that was working exactly as built.

**Four stages, and they were already there.** Nothing about the pipeline is
being invented here; `app/web/tasks.py` has always planned, gathered,
extracted, accepted and logged. This module names those transitions and writes
them down:

    Discovery   — plan the task, render the queries, fetch candidate sources
    Extraction  — pull grounded findings out of each source
    Ingestion   — put them through the acceptance path, keep or refuse
    Ledgering   — write the refusals down, because they are the point

**The engine emits nothing.** This module lives in `app/web/` and is called
from `app/web/tasks.py`; `kriko/` is never handed an emitter, never imports
this, and does not know a pipeline view exists. That is not fastidiousness —
it is G6. A `Researcher` implementation that had to report progress to an
interface would make "add a category" mean "touch the engine", and the
transitions worth watching all happen in the driver anyway, because the driver
is what sequences them.

**Rows are the record.** These tables are what a run leaves behind; nothing in
the app reads them back yet, and the rows are written so that they could be. A run interrupted by a restart is *readable*
afterwards — the same lesson the jobs table already learned, and the reason
`mark_interrupted` exists here too. A live view that is the only record is a
live view that lies the moment anybody closes the window.

**It never breaks the thing it is watching.** Every write here is wrapped:
losing an event is a cosmetic failure, and failing a research run because its
telemetry could not be written would be an instrument that destroys the
experiment. `Emitter` with no connection is a working emitter that records
nothing, which is what the CLI and MCP doors get for free.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.web import state

#: The stages, in order. A closed vocabulary and allowed to be a constant for
#: the reason CLAUDE.md's scalability rule carves out: these are the phases of
#: *making knowledge*, which is a property of the engine's design and does not
#: grow with pack coverage. A fifth stage would be an architecture change, not
#: a new car.
STAGES = ("discovery", "extraction", "ingestion", "ledgering")

#: Events kept per run. Generous — a run reading fifty documents produces a
#: few hundred — and bounded, because this table is the only one here whose
#: size is driven by content rather than by how often somebody presses a
#: button.
MAX_EVENTS_PER_RUN = 2000

#: Runs kept. Older ones are dropped whole, events and stages with them: half
#: an event log is more misleading than none.
MAX_RUNS = 200


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Emitter:
    """A run, being written down as it happens.

    Constructed with a path rather than a connection because the caller is a
    job handler on a worker thread, and the one thing this must not do is
    share a SQLite connection across threads — see `kriko.store.db.connect`
    for what that cost the 0.3.1 release.

    `Emitter(None)` is a working emitter that records nothing. That is what
    makes it safe to thread through a handler that may be driven from the CLI,
    from MCP, or from a test that has no `app.sqlite` at all, without every
    call site growing an `if`.
    """

    def __init__(self, app_state_path: Path | None, *, kind: str, job_id: str | None = None):
        self.path = Path(app_state_path) if app_state_path else None
        self.kind = kind
        self.job_id = job_id
        self.run_id = uuid.uuid4().hex[:16]
        self.stage: str | None = None
        self._conn: sqlite3.Connection | None = None
        self._events = 0

    # ── plumbing ─────────────────────────────────────────────────────────

    def _write(self, fn):
        """Run `fn(conn)`, and swallow whatever it does wrong.

        The instrument must not break the experiment. A locked database, a
        disk that filled, a schema older than this build — none of them is a
        reason for a research run to fail, and all of them would be if this
        raised.
        """
        if self.path is None:
            return None
        try:
            if self._conn is None:
                self._conn = state.connect(self.path)
            result = fn(self._conn)
            self._conn.commit()
            return result
        except Exception:
            return None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # ── the run ──────────────────────────────────────────────────────────

    def begin(self, *, subject_id: str = "", subject: str = "", pack_id: str = "") -> str:
        def go(conn):
            conn.execute(
                "INSERT INTO pipeline_runs "
                "(run_id, job_id, kind, subject_id, subject, pack_id, state, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
                (self.run_id, self.job_id, self.kind, subject_id, subject,
                 pack_id, _now()),
            )
            _prune_runs(conn)

        self._write(go)
        return self.run_id

    def describe(self, **fields) -> None:
        """Fill in what was not knowable when the run opened.

        `plane` is the example: it is decided partway through Discovery, and
        the alternative to updating the row is to delay creating it — which
        would mean a run that crashed during planning left no trace, i.e. the
        exact case somebody is looking at the pipeline view to understand.
        """
        allowed = {"plane", "pack_id", "subject", "subject_id", "tokens"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._write(
            lambda conn: conn.execute(
                f"UPDATE pipeline_runs SET {sets} WHERE run_id = ?",
                (*fields.values(), self.run_id),
            )
        )

    def count(self, **deltas) -> None:
        """Add to the run's totals.

        Additive rather than absolute so a stage does not need to know what
        the ones before it found — Extraction counts findings without being
        told how many sources Discovery produced.
        """
        allowed = {"sources", "findings", "accepted", "refused", "chars"}
        deltas = {k: int(v) for k, v in deltas.items() if k in allowed and v}
        if not deltas:
            return
        sets = ", ".join(f"{k} = {k} + ?" for k in deltas)
        self._write(
            lambda conn: conn.execute(
                f"UPDATE pipeline_runs SET {sets} WHERE run_id = ?",
                (*deltas.values(), self.run_id),
            )
        )

    def finish(self, state_name: str = "done", error: str = "") -> None:
        def go(conn):
            # A stage still open when the run ends failed with it. Closing
            # them here rather than asking every handler to unwind correctly:
            # the interesting failures are exactly the ones that do not.
            conn.execute(
                "UPDATE pipeline_stages SET state = 'failed', ended_at = ? "
                "WHERE run_id = ? AND state = 'running'",
                (_now(), self.run_id),
            )
            conn.execute(
                "UPDATE pipeline_runs SET state = ?, ended_at = ?, error = ? "
                "WHERE run_id = ?",
                (state_name, _now(), error or None, self.run_id),
            )

        self._write(go)
        self.close()

    # ── stages ───────────────────────────────────────────────────────────

    def open_stage(self, stage: str, detail: str = "") -> None:
        if stage not in STAGES:
            raise ValueError(f"not a pipeline stage: {stage!r}")
        # The previous stage closes when the next one opens. A handler that
        # falls through to the next stage has, by definition, finished the one
        # before — and a rule beats asking every call site to remember.
        if self.stage and self.stage != stage:
            self.close_stage()
        self.stage = stage
        self._write(
            lambda conn: conn.execute(
                "INSERT OR REPLACE INTO pipeline_stages "
                "(run_id, stage, seq, state, detail, items, started_at) "
                "VALUES (?, ?, ?, 'running', ?, 0, ?)",
                (self.run_id, stage, STAGES.index(stage), detail, _now()),
            )
        )

    def close_stage(self, state_name: str = "done", detail: str | None = None) -> None:
        stage, self.stage = self.stage, None
        if stage is None:
            return
        sets = "state = ?, ended_at = ?"
        values: list = [state_name, _now()]
        if detail is not None:
            sets += ", detail = ?"
            values.append(detail)
        self._write(
            lambda conn: conn.execute(
                f"UPDATE pipeline_stages SET {sets} WHERE run_id = ? AND stage = ?",
                (*values, self.run_id, stage),
            )
        )

    def skip_stage(self, stage: str, detail: str) -> None:
        """A stage that correctly did nothing.

        Distinct from `done` because the difference matters to the reader:
        the agent plane's `gather` returns nothing *by design*, and an
        Extraction stage showing "done, 0 findings" reads as a failure of the
        thing that is actually the $0 path working as intended.
        """
        self.open_stage(stage, detail)
        self.close_stage("skipped", detail)

    # ── events ───────────────────────────────────────────────────────────

    def event(
        self,
        message: str,
        *,
        level: str = "info",
        source_url: str = "",
        stage: str | None = None,
        **detail,
    ) -> None:
        stage = stage or self.stage or STAGES[0]
        if self._events >= MAX_EVENTS_PER_RUN:
            return
        self._events += 1

        def go(conn):
            conn.execute(
                "INSERT INTO pipeline_events "
                "(run_id, stage, at, level, message, source_url, detail_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.run_id, stage, _now(), level, message, source_url,
                 json.dumps(detail) if detail else None),
            )
            conn.execute(
                "UPDATE pipeline_stages SET items = items + 1 "
                "WHERE run_id = ? AND stage = ?",
                (self.run_id, stage),
            )

        self._write(go)


# ── reading it back ──────────────────────────────────────────────────────


def _prune_runs(conn: sqlite3.Connection) -> None:
    """Drop the oldest runs whole — stages and events with them."""
    stale = [
        row["run_id"]
        for row in conn.execute(
            # `rowid DESC` is not decoration: `started_at` has second
            # resolution, so six runs opened in the same second tie, and a
            # tie broken arbitrarily can delete the run being inserted right
            # now. Insertion order is the only total order available here.
            "SELECT run_id FROM pipeline_runs "
            "ORDER BY started_at DESC, rowid DESC LIMIT -1 OFFSET ?",
            (MAX_RUNS,),
        )
    ]
    for run_id in stale:
        conn.execute("DELETE FROM pipeline_events WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM pipeline_stages WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM pipeline_runs WHERE run_id = ?", (run_id,))


def mark_interrupted(conn: sqlite3.Connection) -> int:
    """A run still `running` at startup was killed, not is running.

    The same startup reconciliation the jobs table does, and for the same
    reason: a process cannot resume a run it has no memory of, and a row that
    says `running` forever renders as a pipeline that never finishes.
    """
    now = _now()
    conn.execute(
        "UPDATE pipeline_stages SET state = 'failed', ended_at = ? "
        "WHERE state = 'running' AND run_id IN "
        "(SELECT run_id FROM pipeline_runs WHERE state = 'running')",
        (now,),
    )
    cursor = conn.execute(
        "UPDATE pipeline_runs SET state = 'interrupted', ended_at = ?, "
        "error = COALESCE(error, 'the app stopped while this run was going') "
        "WHERE state = 'running'",
        (now,),
    )
    conn.commit()
    return cursor.rowcount


def recent_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """The runs this installation recorded, newest first.

    **Nothing read these rows.** This module's own docstring says so — "nothing
    in the app reads them back yet, and the rows are written so that they could
    be" — and the sweep found the same thing a year later: the tables were
    pruned to 200 runs and marked `interrupted` at startup, and no route ever
    selected a single row. So the pipeline's whole account of what a run did was
    write-only, which is a strange kind of record: it survives a restart for the
    benefit of nobody.

    Totals are the denormalised columns, not an aggregate over events — the
    schema says why ("the overview lists runs and must not aggregate thousands
    of events to render a row"), and a run that kept 40 findings is one row.
    """
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
    ]


def run_detail(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """One run with its stages and its events, or `None`.

    Stages come back in `STAGES` order even when one never opened: a stage that
    was never reached is exactly the thing a reader wants to see, and it is
    only visible if the reader knows the whole sequence.
    """
    row = conn.execute(
        "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)
    stages = {one["stage"]: dict(one) for one in conn.execute(
        "SELECT * FROM pipeline_stages WHERE run_id = ?", (run_id,))}
    run["stages"] = [
        stages.get(name, {
            "run_id": run_id, "stage": name, "seq": order, "state": "absent",
            "detail": "", "items": 0, "started_at": "", "ended_at": None,
        })
        for order, name in enumerate(STAGES)
    ]
    run["events"] = [
        dict(one) for one in conn.execute(
            "SELECT * FROM pipeline_events WHERE run_id = ? ORDER BY event_id",
            (run_id,))
    ]
    return run
