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

**Cooperative cancel.** Cancel sets a flag the handler reads between steps.
Killing a thread mid-write is how a half-installed pack happens, so a running
job is asked to stop, never made to.
"""

import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app import operations
from app.web import state


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
    _conn: object

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


#: A handler is `(settings, params, progress) -> dict`. It returns the job's
#: result, raises to fail it, or raises `Cancelled` to stop cleanly.
Handler = Callable[[object, dict, Progress], dict]


class JobRunner:
    def __init__(self, settings, handlers: dict[str, Handler]):
        self.settings = settings
        self.handlers = handlers
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kriko-job")
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
        self._pool.submit(self._run, job_id, kind, params)
        return job_id

    def _run(self, job_id: str, kind: str, params: dict) -> None:
        conn = self._connect()
        progress = Progress(job_id, conn)
        try:
            # The row may have been cancelled while it sat in the queue.
            row = state.get_job(conn, job_id)
            if row is None or row["state"] != state.QUEUED:
                return
            state.start_job(conn, job_id)
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
            ) as outcome:
                result = self.handlers[kind](self.settings, params, progress)
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
            state.finish_job(conn, job_id, state.CANCELLED, message="cancelled")
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
