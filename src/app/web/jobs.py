"""Long work with a state a browser can see.

Two operations actually grow the knowledge base — researching a subject and
building a pack — and before this module both were terminal-only. That
contradicted G6's delivery constraint directly: *every operation must be
operable and inspectable from the desktop and extension with a visible result, error, and
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
kinds in `QUICK_KINDS` are counted apart from research, outside the limit
above, and they too run as many at once as Settings says (a quick look that
waits says why on its row, like any other).

**The agents themselves.** Each run is an agent process, and the host caps
those (`agentresources`, the agent-child budget). The job runner hands the
reader's choice to that budget at every start, so the processes can be as many
as the runs; without it, a choice of four ran two and the rest said "running"
while they waited for a process.

**Cooperative cancel.** Cancel sets a flag the handler reads between steps.
Killing a thread mid-write is how a half-installed pack happens, so a running
job is asked to stop, never made to.
"""

import hashlib
import functools
import sqlite3
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import agentresources, operations, prefs
from app.agentledger import Ledger
from app.version import app_version
from kriko.store.db import connect
from app.web import state


#: Kinds that never write the store or a pack directory, and are short enough
#: that queueing them behind long work would defeat them.
QUICK_KINDS = frozenset({
    "quick_look", "quick_ask", "lookup_ask", "categorize_quick_look",
})

LIVE_DRAFT_CHARS = 8_192
LIVE_DRAFT_INTERVAL = 0.1

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
    if kind == "categorize_quick_look":
        # This writes a validated assignment to app state, not a pack or the
        # knowledge store. It is safe alongside every other job.
        return frozenset()
    if kind in ("research", "verify", "site_register", "agenda_run", "bench",
                "pack_update"):
        return _named("pack", params.get("pack_id"))
    if kind == "pack_build":
        root = str(params.get("root") or "").replace("\\", "/").rstrip("/")
        return _named("pack", root.rsplit("/", 1)[-1])
    if kind in ("pack_author", "pack_amend", "pack_harvest"):
        return frozenset({"drafts"})
    if kind == "compare_ask":
        return _named("compare", params.get("draft_id"))
    if kind == "chat_ask":
        # One turn at a time per conversation; other conversations may run beside it.
        return _named("chat", params.get("thread_id"))
    if kind == "model_pull":
        return _named("model", params.get("model"))
    if kind == "agent_install":
        return _named("agent", params.get("agent_id"))
    return frozenset({EVERYTHING})


def _overlap(one: frozenset[str], other: frozenset[str]) -> bool:
    return bool(one & other) or (EVERYTHING in one and bool(other)) or (
        EVERYTHING in other and bool(one))


_PROMPT_EVALUATOR_SOURCES = (
    "app/web/tasks.py",
    "app/providers/harness.py",
    "app/providers/local_agent.py",
    "app/providers/apiagent.py",
    "app/findings.py",
    "kriko/extract/grounding.py",
    "kriko/ledger/extraction.py",
)


def _hash_prompt_evaluator_sources(source_root: Path) -> dict[str, Any]:
    """Hash logical package-relative sources and report how many were present."""
    digest = hashlib.sha256()
    available = 0
    for relative in _PROMPT_EVALUATOR_SOURCES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            with (source_root / relative).open("rb") as source:
                available += 1
                for block in iter(lambda: source.read(65_536), b""):
                    digest.update(block)
        except OSError:
            digest.update(b"[missing]")
        digest.update(b"\0")
    if available == len(_PROMPT_EVALUATOR_SOURCES):
        status = "available"
    elif available:
        status = "partial"
    else:
        status = "unavailable"
    return {"sha256": digest.hexdigest(), "source_status": status,
            "sources_available": available, "sources_expected": len(_PROMPT_EVALUATOR_SOURCES)}


@functools.cache
def _prompt_evaluator_identity() -> dict[str, Any]:
    """Memoized digest of application-owned prompt and evidence-gate sources."""
    # In a checkout this is ``src/``; in an installed wheel it is the package
    # directory in site-packages. The package-relative names stay identical.
    source_root = Path(__file__).resolve().parents[2]
    return _hash_prompt_evaluator_sources(source_root)


def _manifest_snapshot(settings, params: dict) -> dict:
    """Capture relevant settings and installed-pack identity at submission."""
    stored = {}
    try:
        preference_conn = state.connect(settings.app_state_path)
        try:
            stored = prefs.read(preference_conn)
        finally:
            preference_conn.close()
    except (OSError, sqlite3.Error):
        pass
    backend = str(params.get("backend") or params.get("provider") or "").strip()
    if not backend:
        try:
            from app.web.tasks import default_backend
            backend = str(default_backend(settings.app_state_path))
        except Exception:
            backend = ""
    chosen_harness = str(params.get("harness") or stored.get(prefs.HARNESS) or "").strip()
    model = str(params.get("model") or "").strip()
    if not model:
        if backend == "local":
            model = str(stored.get(prefs.LOCAL_MODEL) or "")
        elif backend == "api" or (backend == "harness" and chosen_harness):
            model_conn: sqlite3.Connection | None = None
            try:
                model_conn = state.connect(settings.app_state_path)
                model = (prefs.for_role(model_conn, "synthesise") if backend == "api"
                         else prefs.for_harness(model_conn, chosen_harness))
                model = model or str(stored.get(prefs.MODEL) or "")
            except Exception:
                model = ""
            finally:
                if model_conn is not None:
                    model_conn.close()
    search = str(params.get("search_provider") or stored.get(prefs.SEARCH) or "").strip()
    snapshot: dict[str, Any] = {
        "implementation": {
            "version": app_version(),
            "prompt_evaluator": _prompt_evaluator_identity(),
        },
        "settings": {"preferred_harness": chosen_harness,
                     "llm_model": str(stored.get(prefs.MODEL) or ""),
                     "local_model": str(stored.get(prefs.LOCAL_MODEL) or ""),
                     "search_provider": search},
        "backend": backend,
        "provider": str(params.get("backend") or params.get("provider") or backend),
        "harness": chosen_harness,
        "model": model,
        "search_provider": search,
    }
    pack_id = str(params.get("pack_id") or "").strip()
    try:
        from kriko.store.db import connect
        store = connect(settings.store_path, read_only=True)
        try:
            if not pack_id and params.get("subject_id"):
                subject = store.execute("SELECT pack_id FROM subjects WHERE subject_id=?",
                                        (str(params["subject_id"]),)).fetchone()
                pack_id = str(subject[0]) if subject else ""
            if pack_id:
                row = store.execute(
                    "SELECT version, content_digest FROM packs WHERE pack_id=?", (pack_id,)
                ).fetchone()
                if row:
                    snapshot["pack"] = {"pack_id": pack_id, "version": row[0],
                                        "content_digest": row[1]}
                    if row[1]:
                        snapshot["pack"]["revision_id"] = f"{pack_id}@{row[1]}"
        finally:
            store.close()
    except (OSError, sqlite3.Error, AttributeError):
        pass
    if pack_id:
        try:
            packs_dir = Path(settings.packs_dir).resolve()
            principle = (packs_dir / pack_id / "research" / "principle.md").resolve()
            principle.relative_to(packs_dir)
            if principle.is_file():
                digest = hashlib.sha256()
                with principle.open("rb") as source:
                    for block in iter(lambda: source.read(65_536), b""):
                        digest.update(block)
                snapshot["principle"] = {"sha256": digest.hexdigest()}
        except (OSError, ValueError, AttributeError):
            pass
    return snapshot


class Cancelled(Exception):
    """Raised by `Progress.check` when the reader asked the job to stop."""

    cancelled = True


@dataclass
class Progress:
    """What a handler is given to report with.

    Deliberately the only channel: a handler that printed to stdout would be
    invisible in the browser, which is the whole thing this module exists to
    fix.
    """

    job_id: str
    _conn: sqlite3.Connection
    _base_message: str = ""
    _draft_message: str = ""
    _draft_last_write: float = 0.0
    ledger: Ledger | None = None
    run_id: str = ""

    def log(self, line: str) -> None:
        state.update_job(self._conn, self.job_id, line=line)

    def set(self, progress: float, message: str = "") -> None:
        if message:
            self._base_message = message
        shown = self._draft_message or message or self._base_message
        state.update_job(
            self._conn,
            self.job_id,
            progress=progress,
            message=shown or None,
        )

    def draft(self, text: str, *, force: bool = False) -> None:
        """Show bounded live prose in the job's existing status field.

        The first fragment is durable immediately. Later updates are
        coalesced to at most ten snapshots per second, so a token stream does
        not rewrite the SQLite row on every delta. Clearing the draft restores
        the phase message; the action log remains a separate, append-only
        record of completed events.
        """
        now = time.monotonic()
        clean = str(text or "")[-(LIVE_DRAFT_CHARS - len("Writing: ")):]
        visible = f"Writing: {clean}" if clean else ""
        if visible == self._draft_message and not force:
            return
        if visible and self._draft_message and not force:
            if now - self._draft_last_write < LIVE_DRAFT_INTERVAL:
                self._draft_message = visible
                return
        self._draft_message = visible
        self._draft_last_write = now
        state.update_job(
            self._conn, self.job_id,
            message=visible or self._base_message or None,
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
        if self.ledger is not None and self.run_id:
            self.ledger.checkpoint(self.run_id, result)


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
    def __init__(self, settings, handlers: Mapping[str, Handler],
                 on_idle: Callable[[], object] | None = None):
        self.settings = settings
        self.handlers = handlers
        #: Called each time the last running job ends, both lanes counted:
        #: what a job held for its run (a loaded model) goes back to the host
        #: then, and never while another job may still be using it.
        self._on_idle = on_idle
        self._active = 0
        # Sized to the ceiling, not to the choice: the choice is read at every
        # start, so raising it in Settings needs no restart, and an idle
        # executor thread costs nothing.
        self._pool = ThreadPoolExecutor(
            max_workers=prefs.MAX_RUN_CONCURRENCY, thread_name_prefix="kriko-job")
        # Sized to the ceiling for the same reason, and gated by the choice in
        # `_pump_quick`. It was a fixed two, so a quick look beyond two waited
        # silently whatever Settings said.
        self._quick = ThreadPoolExecutor(
            max_workers=prefs.MAX_RUN_CONCURRENCY, thread_name_prefix="kriko-quick")
        self._lock = threading.Lock()
        self._retry_lock = threading.Lock()
        self._waiting: list[_Waiting] = []
        self._running: dict[str, frozenset[str]] = {}
        self._quick_waiting: list[_Waiting] = []
        #: Quick looks handed to the quick pool and not yet finished.
        self._quick_running = 0
        self._closed = False
        self.ledger = Ledger(self.settings.app_state_path)

    def _limit(self) -> int:
        """The reader's choice, read now; the agent-child budget follows it."""
        conn = self._connect()
        try:
            limit = prefs.run_concurrency(conn)
        except sqlite3.Error:
            limit = 1
        finally:
            conn.close()
        agentresources.set_agent_children_floor(limit)
        return limit

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
        self._pump_quick()

    def _pump_quick(self) -> None:
        """Start waiting quick looks, as many at once as Settings allow.

        Counted apart from research: a quick look must not queue behind a long
        pack build it was submitted beside. The reader's number is the one
        limit on each lane, so a choice of four means four of each at most.
        """
        limit = self._limit()
        conn = self._connect()
        try:
            with self._lock:
                if self._closed:
                    return
                live = state.live_job_ids(conn, [w.job_id for w in self._quick_waiting])
                start: list[_Waiting] = []
                keep: list[_Waiting] = []
                for one in self._quick_waiting:
                    # A row cancelled while it waited is dispatched anyway, so
                    # `_run` sees the cancel and returns at once. It takes a
                    # count, which `_done` gives back like any other.
                    if one.job_id not in live or self._quick_running < limit:
                        self._quick_running += 1
                        start.append(one)
                        continue
                    reason = (f"waiting: {limit} run(s) at once already "
                              "going; Settings → Runs sets how many")
                    if reason != one.said:
                        one.said = reason
                        state.update_job(conn, one.job_id, message=reason)
                    keep.append(one)
                self._quick_waiting = keep
                for one in start:
                    self._quick.submit(self._run, one.job_id, one.kind, one.params,
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

    def _done(self, job_id: str, kind: str = "") -> None:
        with self._lock:
            if kind in QUICK_KINDS:
                self._quick_running -= 1
            else:
                self._running.pop(job_id, None)
        self._pump()

    # Each job opens its own connection. sqlite3 connections belong to the
    # thread that made them, and the request that submitted a job is long gone
    # by the time the worker picks it up.
    def _connect(self):
        return state.connect(self.settings.app_state_path)

    def recover(self) -> int:
        """Mark orphaned rows `interrupted`. Called once, at app startup."""
        # Classify delivery while a formerly running job still says running.
        # Once state.interrupt_running marks it terminal, recovery would mistake
        # that synthetic interruption for a job that completed before its
        # manifest did, losing the retry-vs-reconcile distinction.
        self.ledger.recover()
        conn = self._connect()
        try:
            count = state.interrupt_running(conn)
        finally:
            conn.close()
        return count

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

    def submit(self, kind: str, params: dict, *, client_request_id: str | None = None,
               snapshot: dict | None = None) -> str:
        if kind not in self.handlers:
            raise KeyError(f"no such job kind: {kind}")
        conn = self._connect()
        try:
            # Request identity, manifest and job row share one SQLite write.
            # A duplicate client ID therefore never leaves an orphan job.
            manifest = self.ledger.reserve_job(
                conn, client_request_id, kind, params,
                snapshot or _manifest_snapshot(self.settings, params),
            )
            job_id = manifest["job_id"]
        finally:
            conn.close()
        if not manifest["created"]:
            return job_id
        if kind in QUICK_KINDS:
            with self._lock:
                self._quick_waiting.append(_Waiting(job_id, kind, params, frozenset()))
            self._pump_quick()
            return job_id
        with self._lock:
            self._waiting.append(
                _Waiting(job_id, kind, params, claims(kind, self._with_pack(params))))
        self._pump()
        return job_id

    def _run(self, job_id: str, kind: str, params: dict, lane: bool = True,
             waited: bool = False) -> None:
        with self._lock:
            self._active += 1
        conn = self._connect()
        manifest = self.ledger.lookup_job(job_id)
        run_id = manifest["run_id"] if manifest else ""
        progress = Progress(job_id, conn, ledger=self.ledger, run_id=run_id)
        try:
            # The row may have been cancelled while it sat in the queue.
            if not state.start_job(conn, job_id):
                job = state.get_job(conn, job_id)
                if job and job["state"] in state.TERMINAL and run_id:
                    self.ledger.finish(run_id, job["state"], result=job.get("result"))
                return
            if run_id:
                ledger_conn = self.ledger.connect()
                try:
                    with ledger_conn:
                        ledger_conn.execute("UPDATE agent_runs SET state='running' WHERE run_id=? AND terminal_at IS NULL",
                                            (run_id,))
                finally:
                    ledger_conn.close()
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
            if run_id:
                usd, tokens = operations.metered(result)
                final = state.get_job(conn, job_id) or {}
                self.ledger.finish(run_id, final.get("state", state.SUCCEEDED),
                                   result=final.get("result") or result,
                                   usage={"usd": usd, "tokens": tokens})
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
            if run_id:
                self.ledger.finish(run_id, state.CANCELLED,
                                   result={**kept, "partial": True} if kept else None)
        except Exception as exc:  # noqa: BLE001 — a failed job is data, not a crash
            # The traceback goes in the log rather than to stderr: an operator
            # reading the job in the app should not have to find the terminal that
            # started the server.
            state.update_job(conn, job_id, line=traceback.format_exc())
            state.finish_job(
                conn, job_id, state.FAILED, message=f"{type(exc).__name__}: {exc}"
            )
            if run_id:
                kept = state.partial_of(conn, job_id)
                self.ledger.finish(run_id, state.FAILED,
                                   result={**kept, "partial": True} if kept else None)
        finally:
            conn.close()
            self._idle_check()
            if lane:
                self._done(job_id, kind)

    def _idle_check(self) -> None:
        with self._lock:
            self._active -= 1
            idle = self._active == 0 and not self._waiting
        if idle and self._on_idle is not None:
            try:
                self._on_idle()
            except Exception:  # noqa: BLE001 - letting go is a courtesy, never a failure
                traceback.print_exc()

    def cancel(self, job_id: str) -> str | None:
        conn = self._connect()
        try:
            answer = state.request_cancel(conn, job_id)
        finally:
            conn.close()
        # A waiting row cancelled is a place in the line given back.
        self._pump()
        return answer

    def concurrency(self) -> dict[str, int]:
        """What the scheduler is doing now, for the jobs and queue screens.

        `running` is what this process has started and not finished, both
        lanes; `queued` is what it is holding back; `concurrency` is the Settings
        choice in force, clamped; `agent_slots` is the host's agent-process
        budget, which is never below the choice unless an operator bounds it
        by hand.
        """
        limit = self._limit()
        with self._lock:
            running = len(self._running) + self._quick_running
            queued = len(self._waiting) + len(self._quick_waiting)
        return {"running": running, "queued": queued, "concurrency": limit,
                "agent_slots": agentresources.agent_child_limit()}

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
            self._waiting.clear()
            self._quick_waiting.clear()
        self._pool.shutdown(wait=wait, cancel_futures=True)
        self._quick.shutdown(wait=wait, cancel_futures=True)
        if self._on_idle is not None:
            try:
                self._on_idle()
            except Exception:  # noqa: BLE001 - quitting goes on regardless
                pass
