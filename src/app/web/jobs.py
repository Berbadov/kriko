"""Long work with a state a browser can see.

Two operations actually grow the knowledge base — researching a subject and
building a pack — and before this module both were terminal-only. That
contradicted G6's delivery constraint directly: *every operation must be
operable and inspectable from the dashboard with a visible result, error, and
durable status*. A `POST` that blocks for four minutes is not that, and neither
is a spinner with nothing behind it.

Three decisions, all of them about failure rather than about throughput:

**Rows first, thread second.** Every state transition is a row in
`app.sqlite` (`state.py`). The thread is how the work happens; the row is what
the work *is*. That is why a killed process leaves `interrupted` jobs and not
mysteries — see `JobRunner.recover`.

**One worker.** `ThreadPoolExecutor(max_workers=1)`. Research is I/O- and
cost-heavy and two concurrent builds writing the same pack directory is a bug
we should not be able to express. Serial is the feature.

**One exception: the quick lane.** A quick look (B148) is one short agent
call that writes nothing to the store, and the reader is waiting on the
listing for it. Queued behind a forty-minute pack author — which it is
usually submitted *beside* — it would be the slowness it exists to fix. So
kinds in `QUICK_KINDS` get their own small pool. Nothing in it writes a pack
directory, which is the only reason the main lane is serial.

**Cooperative cancel.** Cancel sets a flag the handler reads between steps.
Killing a thread mid-write is how a half-installed pack happens, so a running
job is asked to stop, never made to.
"""

import sqlite3
import threading
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app import operations
from app.web import state


#: Kinds that never write the store or a pack directory, and are short enough
#: that queueing them behind long work would defeat them.
QUICK_KINDS = frozenset({"quick_look", "lookup_ask"})


class Cancelled(Exception):
    """Raised by `Progress.check` when the reader asked the job to stop."""


@dataclass
class Progress:
    """What a handler is given to report with.

    Deliberately the only channel: a handler that printed to stdout would be
    invisible in the browser, which is the whole thing this module exists to
    fix.
    """

    job_id: str
    _conn: sqlite3.Connection

    def log(self, line: str) -> None:
        state.update_job(self._conn, self.job_id, line=line)

    def set(self, progress: float, message: str = "") -> None:
        state.update_job(
            self._conn,
            self.job_id,
            progress=progress,
            message=message or None,
        )

    @property
    def cancelled(self) -> bool:
        return state.cancel_requested(self._conn, self.job_id)

    def check(self) -> None:
        """Call between steps. Raises `Cancelled` if the reader asked to stop."""
        if self.cancelled:
            raise Cancelled()

    def replies(self) -> list[str]:
        """What the reader has said to this run since the last time we asked.

        The other direction of `log`, and the one that was missing. A harness
        run streams its thinking out and took nothing in, so a run that paused
        on a question was a window: the reader could watch it be stuck and
        could only stop it. Each line is handed over exactly once.

        Empty is the overwhelmingly common answer, and it costs one indexed
        read — cheap enough to ask between steps, which is the only place it
        can be asked, for the same reason `check` is.
        """
        return state.take_job_messages(self._conn, self.job_id)

    def partial(self, result: dict) -> None:
        """Keep what is finished so far, in case the reader stops here.

        The other half of cooperative cancel, and it was missing. A handler
        asked to stop raised, `_run` wrote `CANCELLED` with no result, and
        everything the handler had gathered died with the stack frame —
        sources fetched, pages read, findings extracted and paid for. The
        reader pressed stop and was charged for work they then had taken away
        from them.

        Called as often as a handler has something worth keeping. Each call
        replaces the last, so a handler passes its running total rather than a
        delta and there is no partial-of-a-partial to reason about.
        """
        state.save_partial(self._conn, self.job_id, result)


#: A handler is `(settings, params, progress) -> dict`. It returns the job's
#: result, raises to fail it, or raises `Cancelled` to stop cleanly.
Handler = Callable[[object, dict, Progress], dict]


def _stopped(kept: dict) -> str:
    """What a cancelled run says it ended with. Never a bare "cancelled"."""
    if not kept:
        return "stopped before anything was finished"
    stage = kept.get("stopped_at") or kept.get("stage") or ""
    counts = ", ".join(
        f"{value} {key}" for key, value in sorted(kept.items())
        if isinstance(value, int) and not isinstance(value, bool) and value
    )
    said = "stopped" + (f" during {stage}" if stage else "")
    return (
        f"{said} — recorded {counts}; see retained results"
        if counts else f"{said}; see retained results"
    )


class JobRunner:
    def __init__(self, settings, handlers: Mapping[str, Handler]):
        self.settings = settings
        self.handlers = handlers
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kriko-job")
        self._quick = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kriko-quick")
        self._lock = threading.Lock()

    # Each job opens its own connection. sqlite3 connections belong to the
    # thread that made them, and the request that submitted a job is long gone
    # by the time the worker picks it up.
    def _connect(self):
        return state.connect(self.settings.app_state_path)

    def recover(self) -> int:
        """Mark orphaned rows `interrupted`. Called once, at app startup."""
        conn = self._connect()
        try:
            return state.interrupt_running(conn)
        finally:
            conn.close()

    def submit(self, kind: str, params: dict) -> str:
        if kind not in self.handlers:
            raise KeyError(f"no such job kind: {kind}")
        conn = self._connect()
        try:
            job_id = state.create_job(conn, kind, params)
        finally:
            conn.close()
        pool = self._quick if kind in QUICK_KINDS else self._pool
        pool.submit(self._run, job_id, kind, params)
        return job_id

    def submit_retry(self, parent_id: str, kind: str, params: dict) -> str:
        """Resolve duplicate retry requests to one durable child.

        The lock covers both the existing-child read and insertion. It also
        leaves the database row as the source of truth, so a retry request
        after a process restart finds the child it created before the restart.
        """
        with self._lock:
            conn = self._connect()
            try:
                existing = state.retry_of(conn, parent_id)
            finally:
                conn.close()
            if existing is not None:
                return existing["job_id"]
            return self.submit(kind, params)

    def _run(self, job_id: str, kind: str, params: dict) -> None:
        conn = self._connect()
        progress = Progress(job_id, conn)
        try:
            # The row may have been cancelled while it sat in the queue.
            if not state.start_job(conn, job_id):
                return
            progress.check()
            # The same row the MCP door writes (B122), so the feed is "what is
            # this installation doing", not "what did the agent ask". A job and
            # a tool call are both operations; that they are started by
            # different things is exactly what `door` records.
            with operations.record(
                self.settings.app_state_path,
                door="job",
                name=kind,
                kind=operations.kind_of(kind),
                arguments=params,
                # So the feed can reach back to the job: its live message, its
                # log, and the one thing the feed could not do before — stop
                # it. Only this door carries one, which is exactly the
                # distinction the button needs.
                job_id=job_id,
            ) as outcome:
                progress.check()
                result = self.handlers[kind](self.settings, params, progress)
                progress.partial(result)
                progress.check()
                outcome["response"] = operations.summarise(result)
                outcome["usd"], outcome["tokens"] = operations.metered(result)
            # No message, so `finish_job`'s COALESCE keeps the handler's own
            # last word. Every handler ends with a `progress.set(1.0, ...)`
            # that says what actually happened — "0 claim(s) kept", "cars
            # built and installed" — and passing "done" overwrote it. That is
            # how the research job came to look like a button that did nothing:
            # it succeeded, produced a brief, and reported a word carrying no
            # information at all.
            state.finish_job(conn, job_id, state.SUCCEEDED, result=result)
        except Cancelled:
            # Whatever the handler checkpointed stays. A cancel is the reader
            # deciding they have enough, or enough of nothing — either way it
            # is a decision about spending more, never an instruction to throw
            # away what is already bought.
            kept = state.partial_of(conn, job_id)
            state.finish_job(
                conn, job_id, state.CANCELLED,
                result={**kept, "partial": True} if kept else None,
                message=_stopped(kept),
            )
        except Exception as exc:  # noqa: BLE001 — a failed job is data, not a crash
            # The traceback goes in the log rather than to stderr: an operator
            # reading the dashboard should not have to find the terminal that
            # started the server.
            state.update_job(conn, job_id, line=traceback.format_exc())
            state.finish_job(
                conn, job_id, state.FAILED, message=f"{type(exc).__name__}: {exc}"
            )
        finally:
            conn.close()

    def cancel(self, job_id: str) -> str | None:
        conn = self._connect()
        try:
            return state.request_cancel(conn, job_id)
        finally:
            conn.close()

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
        self._quick.shutdown(wait=wait, cancel_futures=True)
