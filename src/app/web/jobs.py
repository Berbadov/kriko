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

**Serial per pack, as wide as the reader chose (#133).** This was one worker,
because two concurrent builds writing the same pack directory is a bug we
should not be able to express. That bug is about *the same pack*, and one
worker also serialised a forty-minute author of one category behind the
research of another, which nothing required. So every job now names what it
writes (`claims`), a job starts only when nothing running overlaps its claims,
and how many run at once is the reader's Settings choice
(`prefs.run_concurrency`), one unless they raised it. A kind whose target
cannot be named claims `EVERYTHING` and runs alone, exactly as before: the
default for anything new is the old safety, never the new speed.

Order still holds where it matters. A job that is waiting blocks every later
job whose claims overlap its own, so two runs on one pack start in the order
they were asked for, and a run that needs everything is not starved by a
stream of small ones that keep slipping past it.

**One exception: the quick lane.** A quick look (B148) is one short agent
call that writes nothing to the store, and the reader is waiting on the
listing for it. Queued behind a forty-minute pack author — which it is
usually submitted *beside* — it would be the slowness it exists to fix. So
kinds in `QUICK_KINDS` get their own small pool, outside the limit above.

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

from app import operations, prefs
from kriko.store.db import connect
from app.web import state


#: Kinds that never write the store or a pack directory, and are short enough
#: that queueing them behind long work would defeat them.
QUICK_KINDS = frozenset({"quick_look", "lookup_ask"})

#: The claim that overlaps every other: a job holding it runs alone.
EVERYTHING = "*"


def _named(prefix: str, value) -> frozenset[str]:
    text = str(value or "").strip()
    return frozenset({f"{prefix}:{text}"}) if text else frozenset({EVERYTHING})


def claims(kind: str, params: dict) -> frozenset[str]:
    """What a job writes, as names no other running job may also hold.

    Keyed by the job's own parameters, never by a pack's name written here:
    the pack id is data (CLAUDE.md, no category in code). A kind not listed,
    or a listed one whose parameters do not name a target, claims
    `EVERYTHING`, so a new kind is serial until somebody decides otherwise.

    Drafts are one name for all authoring: an author's draft slug is chosen
    by the agent mid-run, so two authors cannot be told apart up front, and an
    amend may be extending the very draft an author is writing.
    """
    if kind in ("research", "verify", "site_register", "agenda_run", "bench",
                "pack_update"):
        return _named("pack", params.get("pack_id"))
    if kind == "pack_build":
        root = str(params.get("root") or "").replace("\\", "/").rstrip("/")
        return _named("pack", root.rsplit("/", 1)[-1])
    if kind in ("pack_author", "pack_amend"):
        return frozenset({"drafts"})
    if kind == "compare_ask":
        return _named("compare", params.get("draft_id"))
    if kind == "model_pull":
        return _named("model", params.get("model"))
    return frozenset({EVERYTHING})


def _overlap(one: frozenset[str], other: frozenset[str]) -> bool:
    return bool(one & other) or (EVERYTHING in one and bool(other)) or (
        EVERYTHING in other and bool(one))


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


@dataclass
class _Waiting:
    job_id: str
    kind: str
    params: dict
    claims: frozenset[str]
    #: The reason last written to the row, so a pump that finds the same
    #: reason does not write it again on every pass.
    said: str = ""


class JobRunner:
    def __init__(self, settings, handlers: Mapping[str, Handler]):
        self.settings = settings
        self.handlers = handlers
        # Sized to the ceiling, not to the choice: the choice is read at every
        # start, so raising it in Settings needs no restart, and an idle
        # executor thread costs nothing.
        self._pool = ThreadPoolExecutor(
            max_workers=prefs.MAX_RUN_CONCURRENCY, thread_name_prefix="kriko-job")
        self._quick = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kriko-quick")
        self._lock = threading.Lock()
        self._retry_lock = threading.Lock()
        self._waiting: list[_Waiting] = []
        self._running: dict[str, frozenset[str]] = {}
        self._closed = False

    def _limit(self) -> int:
        conn = self._connect()
        try:
            return prefs.run_concurrency(conn)
        except sqlite3.Error:
            return 1
        finally:
            conn.close()

    def _pump(self) -> None:
        """Start every waiting job that may start now, oldest first.

        Called on submit, on every finish and on cancel: those are the only
        moments the answer can change (besides the Settings choice, which the
        next of them picks up).
        """
        limit = self._limit()
        conn = self._connect()
        try:
            with self._lock:
                if self._closed:
                    return
                live = state.live_job_ids(conn, [w.job_id for w in self._waiting])
                # A row cancelled while it waited holds nothing: dispatch it
                # anyway so `_run` sees the cancel and returns at once.
                start: list[_Waiting] = []
                keep: list[_Waiting] = []
                ahead: frozenset[str] = frozenset()
                holding = list(self._running.values())
                for one in self._waiting:
                    gone = one.job_id not in live
                    if gone:
                        start.append(one)
                        continue
                    if len(self._running) >= limit:
                        reason = (f"waiting: {limit} run(s) at once already "
                                  "going; Settings → Runs sets how many")
                    elif any(_overlap(one.claims, held) for held in holding) or \
                            _overlap(one.claims, ahead):
                        reason = ("waiting for the run ahead of it on the same "
                                  "pack to finish" if EVERYTHING not in one.claims
                                  else "waiting to run alone: it may touch every pack")
                    else:
                        start.append(one)
                        self._running[one.job_id] = one.claims
                        holding.append(one.claims)
                        continue
                    ahead = ahead | one.claims
                    if reason != one.said:
                        one.said = reason
                        state.update_job(conn, one.job_id, message=reason)
                    keep.append(one)
                self._waiting = keep
                for one in start:
                    self._pool.submit(self._run, one.job_id, one.kind, one.params,
                                      True, bool(one.said))
        finally:
            conn.close()

    def _with_pack(self, params: dict) -> dict:
        """The params, with the pack named when only the subject was.

        A research or verify request may name just a subject, and the handler
        finds its pack itself. The claim has to find the same pack, or two
        runs on one pack would pass as two runs on nothing in particular.
        Unknown subject: left as it is, which claims `EVERYTHING`.
        """
        subject = str(params.get("subject_id") or "").strip()
        if params.get("pack_id") or not subject:
            return params
        try:
            store = connect(self.settings.store_path, read_only=True)
        except (sqlite3.Error, OSError):
            return params
        try:
            row = store.execute(
                "SELECT pack_id FROM subjects WHERE subject_id = ?", (subject,)
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            store.close()
        return {**params, "pack_id": row[0]} if row else params

    def _done(self, job_id: str) -> None:
        with self._lock:
            self._running.pop(job_id, None)
        self._pump()

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

    def retry(self, kind: str, params: dict) -> str:
        """One child per parent, including a child that has already finished.

        Serialize lookup and submission independently of the scheduling lock:
        submit pumps the queue and must be able to take that lock itself.
        """
        with self._retry_lock:
            conn = self._connect()
            try:
                existing = state.live_retry_of(conn, params["retry_of"])
            finally:
                conn.close()
            return existing["job_id"] if existing else self.submit(kind, params)

    def submit(self, kind: str, params: dict) -> str:
        if kind not in self.handlers:
            raise KeyError(f"no such job kind: {kind}")
        conn = self._connect()
        try:
            job_id = state.create_job(conn, kind, params)
        finally:
            conn.close()
        if kind in QUICK_KINDS:
            self._quick.submit(self._run, job_id, kind, params, False)
            return job_id
        with self._lock:
            self._waiting.append(
                _Waiting(job_id, kind, params, claims(kind, self._with_pack(params))))
        self._pump()
        return job_id

    def _run(self, job_id: str, kind: str, params: dict, lane: bool = True,
             waited: bool = False) -> None:
        conn = self._connect()
        progress = Progress(job_id, conn)
        try:
            # The row may have been cancelled while it sat in the queue.
            if not state.start_job(conn, job_id):
                return
            if waited:
                # A row that waited still says why; it is not waiting now.
                # Blank, so the handler's first `set` is the next word on it.
                state.update_job(conn, job_id, message="")
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
            if lane:
                self._done(job_id)

    def cancel(self, job_id: str) -> str | None:
        conn = self._connect()
        try:
            answer = state.request_cancel(conn, job_id)
        finally:
            conn.close()
        # A waiting row cancelled is a place in the line given back.
        self._pump()
        return answer

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
            self._waiting.clear()
        self._pool.shutdown(wait=wait, cancel_futures=True)
        self._quick.shutdown(wait=wait, cancel_futures=True)
