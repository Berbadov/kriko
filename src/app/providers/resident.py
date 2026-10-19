"""Resident, isolated workers for the agents that are not Codex.

`codex_transport` keeps one Codex app-server alive and opens a fresh thread per
request. This module does the same for the other agents, over the persistent
protocol each one actually has:

* **Claude Code** reads `stream-json` messages on stdin for as long as it runs.
  One process serves many requests; between two of them the worker is sent
  `/clear`, which the CLI answers with `conversation_reset` and a new session
  id. A request therefore never sees the previous request's conversation.
* **Mistral Vibe** ships `vibe-acp`, an Agent Client Protocol server. Every
  request opens a fresh ACP session (`session/new`), so context is isolated by
  the protocol itself.

An agent with no persistent protocol (Antigravity's `agy`: print mode only) has
no wire here and stays on its process adapter; asking for `persistent` there
fails before anything is sent, and `auto` uses the process.

The pool is the part both wires share. A worker is reused only when its whole
profile identity matches; a worker that has to be interrupted and does not
stop is quarantined and killed; a request whose delivery is uncertain is never
replayed. The failure vocabulary is `codex_transport`'s, so one `except` in the
harness covers every agent.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from app import agentresources
from app.agentresources import slot
from app.processcontrol import contained_popen, create_job_object
from app.providers.codex_transport import (
    CodexTransportError,
    DeliveryUncertain,
    TransportUnavailable,
    TurnCancelled,
    TurnRejected,
    _PropagateCallbackError,
    _close_job,
    _error_message,
    _terminate,
    _total_memory_gib,
)

DeliveryCallback = Callable[..., None]

_MAX_BUFFERED_MESSAGES = 8192
_MAX_RETAINED_EVENTS = 4096
_STOP_GRACE = 2.0


class ProtocolAbsent(TransportUnavailable):
    """This agent, or this installed copy of it, has no persistent protocol.

    A fact about the install and not a failure: `auto` uses a process without
    remark, and `persistent` reports it. A worker that *should* have started and
    did not is a plain `TransportUnavailable`, which `auto` mentions.
    """


class ResidentError(CodexTransportError):
    """The agent ended the request in a way it reported (refusal, limit)."""


@dataclass(frozen=True)
class ResidentProfile:
    """Everything that makes one worker different from another.

    ``argv`` is the complete launch vector and ``env`` the complete child
    environment, both built by the caller from the same rules the process
    adapter uses, so a resident worker is the process adapter's child kept
    alive and nothing wider. ``fingerprint`` pins the account/config snapshot
    the caller derived the environment from. Environment values may be
    credentials: they enter the identity as a hash and nowhere else.
    """

    wire: str
    argv: tuple[str, ...]
    cwd: str
    env: Mapping[str, str] = field(default_factory=dict)
    model: str = ""
    effort: str = ""
    fingerprint: str = ""

    def identity(self) -> str:
        exe = Path(self.argv[0]) if self.argv else Path("")
        try:
            stat = exe.resolve().stat()
            stamp: tuple[Any, ...] = (str(exe.resolve()), stat.st_size, stat.st_mtime_ns)
        except OSError:
            stamp = (str(exe), None, None)
        payload = {
            "wire": self.wire, "argv": list(self.argv), "exe": stamp,
            "cwd": str(Path(self.cwd).resolve()),
            "env": hashlib.sha256(json.dumps(sorted(self.env.items())).encode()).hexdigest(),
            "model": self.model, "effort": self.effort, "fingerprint": self.fingerprint,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ResidentRequest:
    prompt: str
    timeout: float = 300.0
    #: A decoded protocol message, for callers that want structure.
    on_event: Callable[[Mapping[str, Any]], None] | None = None
    #: The raw NDJSON line, for callers that already narrate the process
    #: adapter's own output (Claude Code's `stream-json`).
    on_line: Callable[[str], None] | None = None
    on_delivery: DeliveryCallback | None = None
    #: One short sentence about what the agent is doing.
    on_action: Callable[[str], None] | None = None
    on_text: Callable[[str], None] | None = None
    check_cancelled: Callable[[], None] | None = None


@dataclass(frozen=True)
class ResidentResult:
    text: str
    context_id: str
    turn_id: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    #: The agent's own end-of-turn object, where it prints one (Claude Code's
    #: `result`). The harness reads cost, usage and errors out of it exactly as
    #: it does from the process adapter's output.
    envelope: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class _Worker:
    profile: ResidentProfile
    identity: str
    process: subprocess.Popen[str]
    incoming: queue.Queue[tuple[dict[str, Any], str] | BaseException]
    wire: "Wire"
    job: int | None = None
    worker_start_ms: float = 0.0
    handshake_ms: float = 0.0
    startup_queue_ms: float = 0.0
    #: When the process was asked to start, and how long until it first printed
    #: anything: the agent's own readiness, recorded for the run's facts.
    spawned_at: float = 0.0
    first_line_ms: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    next_id: int = 0
    last_used: float = field(default_factory=time.monotonic)
    busy: bool = False
    quarantined: bool = False
    #: Whatever the wire needs to remember between requests.
    state: dict[str, Any] = field(default_factory=dict)
    thread: threading.Thread | None = None
    resource_guard: AbstractContextManager[None] | None = None

    def write_raw(self, value: Mapping[str, Any]) -> None:
        if self.process.stdin is None:
            raise ResidentError("the agent's stdin is unavailable")
        with self.write_lock:
            self.process.stdin.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def next_message(self, timeout: float | None = None) -> tuple[dict[str, Any], str] | None:
        try:
            value = self.incoming.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(value, BaseException):
            raise CodexTransportError(str(value)) from value
        return value

    # JSON-RPC, for the wires that speak it.

    def request(self, method: str, params: Mapping[str, Any]) -> int:
        self.next_id += 1
        self.write_raw({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": dict(params)})
        return self.next_id

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self.write_raw({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def rpc(self, method: str, params: Mapping[str, Any], timeout: float = 30) -> Mapping[str, Any]:
        request_id = self.request(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.next_message(timeout=max(0.01, min(0.1, deadline - time.monotonic())))
            if got is None or got[0].get("id") != request_id or "method" in got[0]:
                continue
            message = got[0]
            if "error" in message:
                raise TurnRejected(_error_message(message["error"]))
            result = message.get("result", {})
            return result if isinstance(result, Mapping) else {}
        raise TimeoutError(f"timed out waiting for {method}")


@dataclass(frozen=True)
class _Acquisition:
    worker: _Worker
    reused: bool
    queue_ms: float


class Wire:
    """What differs between agents: the handshake, one turn, and noise."""

    name = ""
    #: Longest line the reader accepts. Claude Code prints its tool list in one.
    max_line = 64 * 1024
    #: A bound on how long a worker may idle before the reaper releases it.

    def handshake(self, worker: _Worker, timeout: float) -> None:
        raise NotImplementedError

    def keep(self, message: Mapping[str, Any]) -> bool:
        """False for chatter that is never read; dropped before it is queued."""
        return True

    def server_request(self, worker: _Worker, message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The reply to something the agent asked of Kriko. Kriko grants nothing."""
        return None

    def run_turn(
        self, pool: "ResidentTransport", worker: _Worker, req: ResidentRequest,
        cancel: threading.Event, deadline: float, metrics: dict[str, Any],
    ) -> ResidentResult:
        raise NotImplementedError


class ResidentTransport:
    """Thread-safe pool of resident agent workers, one wire per profile."""

    def __init__(
        self,
        *,
        idle_seconds: float = 90,
        low_memory_idle_seconds: float = 20,
        max_warm_workers: int | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        wires: Mapping[str, Wire] | None = None,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.low_memory_idle_seconds = low_memory_idle_seconds
        self.max_warm_workers = max_warm_workers or 1
        self._popen = popen
        self._wires = dict(wires) if wires is not None else {
            "claude": ClaudeWire(), "acp": AcpWire(),
        }
        self._workers: list[_Worker] = []
        self._lock = threading.RLock()
        self._available = threading.Condition(self._lock)
        self._starting = 0
        self._max_workers: int | None = None
        self._closed = False
        self._reaper_stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, name="resident-worker-reaper", daemon=True)
        self._reaper.start()

    @property
    def max_workers(self) -> int:
        """How many workers may be alive at once, read live.

        The reader's run choice can change between two requests, so this is
        the host's current agent-child budget and not a number taken at
        construction; a fixed value would keep the pool at two after Settings
        said four. Assigning it pins the value (a test's one slot).
        """
        if self._max_workers is not None:
            return self._max_workers
        return agentresources.agent_child_limit()

    @max_workers.setter
    def max_workers(self, value: int | None) -> None:
        self._max_workers = value

    # ── one request ──────────────────────────────────────────────────────────

    def run(
        self,
        profile: ResidentProfile,
        request: ResidentRequest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ResidentResult:
        """Run one independent request on a worker with this exact profile."""
        run_started = time.monotonic()
        wire = self._wires.get(profile.wire)
        if wire is None:
            raise TransportUnavailable(f"no persistent protocol for {profile.wire!r}")
        if not request.prompt.strip():
            raise ValueError("prompt must not be empty")
        cancel = cancel_event or threading.Event()

        def check_before_spawn() -> None:
            if cancel.is_set():
                raise TurnCancelled("cancelled before the agent started")
            try:
                _check(request.check_cancelled)
            except BaseException as exc:
                raise _PropagateCallbackError(exc) from None

        _delivery(request.on_delivery, "not_sent", "", "", None)
        deadline = run_started + request.timeout
        try:
            acquisition = self._acquire(profile, wire, check_before_spawn, deadline)
        except _PropagateCallbackError as exc:
            raise exc.original
        worker = acquisition.worker
        try:
            with worker.lock:
                if cancel.is_set():
                    raise TurnCancelled("cancelled before delivery")
                worker.busy = True
                worker.last_used = time.monotonic()
                metrics: dict[str, Any] = {
                    "queue_ms": acquisition.queue_ms + (worker.startup_queue_ms if not acquisition.reused else 0.0),
                    "worker_start_ms": 0.0 if acquisition.reused else worker.worker_start_ms,
                    "handshake_ms": 0.0 if acquisition.reused else worker.handshake_ms,
                    "reused_worker": acquisition.reused,
                    "wire": wire.name,
                }
                result = wire.run_turn(self, worker, request, cancel, deadline, metrics)
                metrics["total_ms"] = (time.monotonic() - run_started) * 1000
                # How long the agent took to be ready for this prompt: a reused
                # worker's `/clear` round trip, or a new worker's start to its
                # first message. Same meaning as a process's first output line.
                metrics["ready_ms"] = (metrics.get("reset_ms", 0.0) if acquisition.reused
                                       else worker.first_line_ms)
                return result
        finally:
            with self._lock:
                worker.busy = False
                worker.last_used = time.monotonic()
                if worker.quarantined or self._closed or worker.process.poll() is not None:
                    self._discard_locked(worker)
                self._available.notify_all()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._reaper_stop.set()
            workers = list(self._workers)
            self._workers.clear()
            self._available.notify_all()
        for worker in workers:
            with self._lock:
                self._discard_locked(worker)
        if wait and self._reaper is not threading.current_thread():
            self._reaper.join(timeout=2)

    shutdown = close

    def release_idle(self, limit: int | None = None) -> int:
        """Free idle workers' child slots for another adapter. Busy ones stay."""
        with self._available:
            idle = [w for w in self._workers if not w.busy]
            if limit is not None:
                idle = idle[:max(0, limit)]
            for worker in idle:
                self._workers.remove(worker)
            if idle:
                self._available.notify_all()
        for worker in idle:
            _release(worker)
        return len(idle)

    def worker_count(self) -> int:
        with self._lock:
            return len(self._workers)

    def _acquire(
        self, profile: ResidentProfile, wire: Wire,
        check: Callable[[], None] | None, deadline: float,
    ) -> _Acquisition:
        identity = profile.identity()
        requested_at = time.monotonic()
        while True:
            evict: _Worker | None = None
            with self._available:
                if self._closed:
                    raise CodexTransportError("transport is closed")
                if check:
                    check()
                for worker in self._workers:
                    if (worker.identity == identity and not worker.busy and not worker.quarantined
                            and worker.process.poll() is None):
                        worker.busy = True
                        return _Acquisition(worker, True, (time.monotonic() - requested_at) * 1000)
                evict = next((w for w in self._workers if not w.busy), None)
                if evict is not None:
                    self._workers.remove(evict)
                elif len(self._workers) + self._starting < self.max_workers:
                    self._starting += 1
                    break
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("timed out waiting for an idle agent worker")
                    self._available.wait(min(0.05, remaining))
                    continue
            if evict is not None:
                _release(evict)
        try:
            queue_ms = (time.monotonic() - requested_at) * 1000
            worker = self._start_worker(profile, wire, identity, check, deadline)
        except BaseException:
            with self._available:
                self._starting -= 1
                self._available.notify_all()
            raise
        with self._available:
            self._starting -= 1
            if self._closed:
                self._discard_locked(worker)
                self._available.notify_all()
                raise CodexTransportError("transport closed during worker startup")
            worker.busy = True
            self._workers.append(worker)
            self._available.notify_all()
            return _Acquisition(worker, False, queue_ms)

    def _start_worker(
        self, profile: ResidentProfile, wire: Wire, identity: str,
        check: Callable[[], None] | None, deadline: float,
    ) -> _Worker:
        if not profile.argv or not Path(profile.argv[0]).exists():
            raise TransportUnavailable("the agent executable is unavailable")
        cwd = Path(profile.cwd).resolve()
        if not cwd.is_dir():
            raise ResidentError("the worker's working folder must be an existing directory")
        resource_guard = slot("agent_child", key=identity, check=check,
                              timeout=max(0.0, deadline - time.monotonic()))
        wait_started = time.monotonic()
        resource_guard.__enter__()
        startup_queue_ms = (time.monotonic() - wait_started) * 1000
        job: int | None = None
        try:
            job = create_job_object() if self._popen is subprocess.Popen else None
            spawn_started = time.monotonic()
            process = contained_popen(
                list(profile.argv), factory=self._popen, job=job, resource_kind=None,
                cwd=str(cwd), env=dict(profile.env),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except BaseException as exc:
            resource_guard.__exit__(None, None, None)
            _close_job(job)
            if isinstance(exc, (TimeoutError, TurnCancelled, _PropagateCallbackError)):
                raise
            raise TransportUnavailable(f"could not start {wire.name} worker: {exc}") from exc
        worker = _Worker(
            profile, identity, process, queue.Queue(maxsize=_MAX_BUFFERED_MESSAGES), wire, job=job,
            worker_start_ms=(time.monotonic() - spawn_started) * 1000,
            startup_queue_ms=startup_queue_ms, spawned_at=spawn_started,
        )
        worker.resource_guard = resource_guard
        worker.thread = threading.Thread(target=self._read_loop, args=(worker,),
                                         name=f"{wire.name}-worker-reader", daemon=True)
        try:
            worker.thread.start()
        except BaseException as exc:
            _release(worker)
            raise TransportUnavailable(f"could not start the {wire.name} protocol reader: {exc}") from exc
        handshake_started = time.monotonic()
        try:
            wire.handshake(worker, min(20.0, max(0.0, deadline - time.monotonic())))
            worker.handshake_ms = (time.monotonic() - handshake_started) * 1000
        except TimeoutError:
            _release(worker)
            raise
        except BaseException as exc:
            _release(worker)
            raise TransportUnavailable(f"{wire.name} initialization failed: {exc}") from exc
        return worker

    # ── the reader ───────────────────────────────────────────────────────────

    def _read_loop(self, worker: _Worker) -> None:
        wire = worker.wire
        assert worker.process.stdout is not None
        try:
            while True:
                line = worker.process.stdout.readline(wire.max_line + 1)
                if not line:
                    break
                if worker.first_line_ms is None:
                    worker.first_line_ms = (time.monotonic() - worker.spawned_at) * 1000
                if len(line) > wire.max_line:
                    _fail(worker, f"{wire.name} message exceeds the {wire.max_line // 1024} KiB limit")
                    _terminate(worker.process, worker.job)
                    worker.job = None
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                reply = wire.server_request(worker, message)
                if reply is not None:
                    try:
                        worker.write_raw(reply)
                    except Exception:
                        pass
                    continue
                if not wire.keep(message):
                    continue
                try:
                    worker.incoming.put_nowait((message, line.rstrip("\r\n")))
                except queue.Full:
                    _fail(worker, f"{wire.name} exceeded the buffered event limit")
                    _terminate(worker.process, worker.job)
                    worker.job = None
                    break
        except BaseException as exc:
            _fail(worker, str(exc))
        finally:
            _fail(worker, f"{wire.name} worker exited")

    def _reap_loop(self) -> None:
        while not self._reaper_stop.wait(5):
            self._reap_once()

    def _reap_once(self) -> None:
        now = time.monotonic()
        idle_limit = self.low_memory_idle_seconds if _total_memory_gib() <= 8 else self.idle_seconds
        with self._lock:
            workers = [w for w in self._workers if not w.busy]
            exited = [w for w in workers if w.process.poll() is not None]
            aged = [w for w in workers if now - w.last_used >= idle_limit]
            retained = [w for w in workers if w not in exited and w not in aged]
            excess = max(0, len(retained) - self.max_warm_workers)
            lru = sorted(retained, key=lambda w: w.last_used)
            evict = {id(w): w for w in exited + aged + lru[:excess]}
            for worker in evict.values():
                self._workers.remove(worker)
            self._available.notify_all()
        # Termination can wait for a process tree to exit. Detach under the
        # pool lock, then do that wait outside it so startup, cancellation and
        # foreground requests never queue behind idle cleanup.
        for worker in evict.values():
            _release(worker)

    def _discard_locked(self, worker: _Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        _release(worker)

    # ── shared turn machinery ────────────────────────────────────────────────

    def pump(
        self, worker: _Worker, req: ResidentRequest, cancel: threading.Event, deadline: float,
        handle: Callable[[dict[str, Any], str], Any], interrupt: Callable[[], None],
        stopped: Callable[[dict[str, Any]], bool], what: str,
    ) -> Any:
        """Feed messages to `handle` until it returns something other than None.

        Cancellation, the caller's own `check_cancelled` and the absolute
        deadline are polled every 100 ms. On any of them the turn is
        interrupted and given two seconds to say it stopped; a worker that
        does not is quarantined, because its next request would otherwise
        read the tail of this one.
        """
        while True:
            try:
                _check(req.check_cancelled)
            except BaseException as callback_error:
                interrupt()
                worker.quarantined = not self.wait_stopped(worker, stopped)
                raise _PropagateCallbackError(callback_error) from None
            if cancel.is_set():
                interrupt()
                worker.quarantined = not self.wait_stopped(worker, stopped)
                raise TurnCancelled(f"{what} cancelled" if not worker.quarantined
                                    else f"{what} did not stop; worker quarantined")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                interrupt()
                worker.quarantined = True
                raise DeliveryUncertain(f"{what} timed out; worker quarantined")
            got = worker.next_message(timeout=min(0.1, remaining))
            if got is None:
                continue
            outcome = handle(*got)
            if outcome is not None:
                return outcome

    def wait_stopped(self, worker: _Worker, stopped: Callable[[dict[str, Any]], bool]) -> bool:
        end = time.monotonic() + _STOP_GRACE
        while time.monotonic() < end:
            try:
                got = worker.next_message(timeout=min(0.1, max(0.01, end - time.monotonic())))
            except CodexTransportError:
                return False
            if got is not None and stopped(got[0]):
                return True
        return False


# ── Claude Code ──────────────────────────────────────────────────────────────

#: Event types Claude Code prints that nothing here reads.
_CLAUDE_NOISE = frozenset({
    "rate_limit_event", "autocompact_state", "active_goal", "conversation_reset",
})


class ClaudeWire(Wire):
    """`claude -p --input-format stream-json --output-format stream-json`."""

    name = "claude"
    # `system/init` lists every tool and skill in one line.
    max_line = 8 * 1024 * 1024
    clear_timeout = 20.0

    def handshake(self, worker: _Worker, timeout: float) -> None:
        # Nothing to negotiate: the CLI announces itself with the first turn.
        if worker.process.poll() is not None:
            raise TransportUnavailable("the process exited at startup")
        worker.state["dirty"] = False

    def keep(self, message: Mapping[str, Any]) -> bool:
        return message.get("type") not in _CLAUDE_NOISE

    def server_request(self, worker: _Worker, message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if message.get("type") == "control_request":
            return {"type": "control_response", "response": {
                "subtype": "error", "request_id": message.get("request_id"),
                "error": "client capability denied"}}
        return None

    @staticmethod
    def _user(text: str) -> dict[str, Any]:
        return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}

    def _interrupt(self, worker: _Worker) -> None:
        worker.next_id += 1
        try:
            worker.write_raw({"type": "control_request", "request_id": f"kriko-{worker.next_id}",
                              "request": {"subtype": "interrupt"}})
        except Exception:
            pass

    def _clear(self, pool: ResidentTransport, worker: _Worker, req: ResidentRequest,
               cancel: threading.Event, deadline: float) -> None:
        """Drop the previous request's conversation before this one is sent.

        Done before the new prompt rather than after the old reply, so a
        worker that crashed or was interrupted mid-clear is never handed a
        request. Failing here is safe to fall back from: nothing was sent.
        """
        try:
            worker.write_raw(self._user("/clear"))
            until = min(deadline, time.monotonic() + self.clear_timeout)
            pool.pump(
                worker, req, cancel, until,
                lambda message, raw: True if message.get("type") == "result" else None,
                lambda: self._interrupt(worker), lambda m: m.get("type") == "result",
                "conversation reset",
            )
        except (TurnCancelled, _PropagateCallbackError):
            raise
        except BaseException as exc:
            worker.quarantined = True
            raise TransportUnavailable(f"could not reset the conversation: {exc}") from exc
        worker.state["dirty"] = False

    def run_turn(
        self, pool: ResidentTransport, worker: _Worker, req: ResidentRequest,
        cancel: threading.Event, deadline: float, metrics: dict[str, Any],
    ) -> ResidentResult:
        delivery = req.on_delivery
        sent = False
        context_id = ""
        events = 0
        try:
            try:
                if worker.state.get("dirty"):
                    started = time.monotonic()
                    self._clear(pool, worker, req, cancel, deadline)
                    metrics["reset_ms"] = (time.monotonic() - started) * 1000
                if cancel.is_set():
                    raise TurnCancelled("cancelled before delivery")
                try:
                    _check(req.check_cancelled)
                except BaseException as callback_error:
                    raise _PropagateCallbackError(callback_error) from None
            except _PropagateCallbackError:
                raise
            _delivery(delivery, "not_sent", "", "", None)
            _delivery(delivery, "unknown", "", "", "prompt write pending")
            sent = True
            sent_at = time.monotonic()
            worker.state["dirty"] = True
            worker.write_raw(self._user(req.prompt))
            state: dict[str, Any] = {"accepted": False, "first_text": None}

            def handle(message: dict[str, Any], raw: str) -> Any:
                nonlocal context_id, events
                kind = message.get("type")
                if not state["accepted"]:
                    state["accepted"] = True
                    metrics["turn_accept_ms"] = (time.monotonic() - sent_at) * 1000
                    _delivery(delivery, "accepted", str(message.get("session_id") or ""), "", None)
                events += 1
                # Partial-token frames are the answer arriving, one per token;
                # capping them fails any long answer. The deadline bounds them.
                if events > _MAX_RETAINED_EVENTS and kind != "stream_event":
                    raise ResidentError("the agent exceeded the per-turn event limit")
                sid = message.get("session_id")
                if isinstance(sid, str) and sid:
                    context_id = sid
                if req.on_line:
                    req.on_line(raw)
                if req.on_event:
                    req.on_event(message)
                if kind == "stream_event":
                    event = message.get("event")
                    delta = event.get("delta") if isinstance(event, Mapping) else None
                    if (isinstance(delta, Mapping) and delta.get("type") == "text_delta"
                            and isinstance(delta.get("text"), str)):
                        if state["first_text"] is None:
                            state["first_text"] = (time.monotonic() - sent_at) * 1000
                            metrics["first_text_ms"] = state["first_text"]
                        if req.on_text:
                            req.on_text(delta["text"])
                    return None
                if kind == "result":
                    return message
                return None

            envelope = pool.pump(
                worker, req, cancel, deadline, handle,
                lambda: self._interrupt(worker), lambda m: m.get("type") == "result",
                "the turn",
            )
            if cancel.is_set():
                raise TurnCancelled("the turn was cancelled")
            usage = envelope.get("usage") if isinstance(envelope.get("usage"), Mapping) else {}
            text = envelope.get("result")
            metrics["event_count"] = events
            return ResidentResult(
                text if isinstance(text, str) else "", context_id,
                str(envelope.get("uuid") or envelope.get("session_id") or ""),
                dict(usage), dict(envelope), metrics,
            )
        except _PropagateCallbackError as exc:
            raise exc.original
        except (TurnCancelled, TurnRejected):
            raise
        except DeliveryUncertain:
            if sent:
                _delivery(delivery, "unknown", context_id, "", "delivery outcome could not be established")
            worker.quarantined = True
            raise
        except TimeoutError:
            worker.quarantined = True
            raise
        except TransportUnavailable:
            raise
        except ResidentError:
            worker.quarantined = True
            raise
        except BaseException as exc:
            if sent:
                _delivery(delivery, "unknown", context_id, "", str(exc))
                worker.quarantined = True
                raise DeliveryUncertain(f"delivery became uncertain: {exc}") from exc
            raise TransportUnavailable(str(exc)) from exc


# ── Agent Client Protocol ────────────────────────────────────────────────────


class AcpWire(Wire):
    """Agent Client Protocol over stdio: JSON-RPC 2.0, one session per request."""

    name = "acp"
    protocol_version = 1

    def handshake(self, worker: _Worker, timeout: float) -> None:
        result = worker.rpc("initialize", {
            "protocolVersion": self.protocol_version,
            # Kriko lends the agent no files and no terminal.
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                   "terminal": False},
            "clientInfo": {"name": "kriko", "title": "Kriko research", "version": "1"},
        }, timeout=timeout)
        version = result.get("protocolVersion")
        if not isinstance(version, int) or version < 1:
            raise TransportUnavailable("the agent did not answer with a protocol version")
        capabilities = result.get("agentCapabilities")
        sessions = capabilities.get("sessionCapabilities") if isinstance(capabilities, Mapping) else None
        worker.state["can_close"] = bool(isinstance(sessions, Mapping) and sessions.get("close") is not None)

    def server_request(self, worker: _Worker, message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if "method" not in message or "id" not in message:
            return None
        if message["method"] == "session/request_permission":
            # A permission request is an attempt to use a tool. Refuse it by
            # choosing the agent's own reject option; with none offered, the
            # protocol's "cancelled" outcome.
            options = (message.get("params") or {}).get("options") or ()
            reject = next((o.get("optionId") for o in options
                           if isinstance(o, Mapping) and str(o.get("kind", "")).startswith("reject")), None)
            outcome = ({"outcome": "selected", "optionId": reject} if reject
                       else {"outcome": "cancelled"})
            return {"jsonrpc": "2.0", "id": message["id"], "result": {"outcome": outcome}}
        return {"jsonrpc": "2.0", "id": message["id"],
                "error": {"code": -32601, "message": "client capability denied"}}

    def run_turn(
        self, pool: ResidentTransport, worker: _Worker, req: ResidentRequest,
        cancel: threading.Event, deadline: float, metrics: dict[str, Any],
    ) -> ResidentResult:
        delivery = req.on_delivery
        profile = worker.profile
        session_id = ""
        prompt_id: int | None = None
        sent = False
        parts: list[str] = []
        usage: dict[str, Any] = {}
        events = 0
        try:
            if cancel.is_set():
                raise TurnCancelled("cancelled before the session started")
            try:
                _check(req.check_cancelled)
            except BaseException as callback_error:
                raise _PropagateCallbackError(callback_error) from None
            started = time.monotonic()
            created = worker.rpc("session/new", {"cwd": str(Path(profile.cwd).resolve()), "mcpServers": []},
                                 timeout=_remaining(deadline))
            metrics["session_start_ms"] = (time.monotonic() - started) * 1000
            session_id = str(created.get("sessionId") or "")
            if not session_id:
                raise ResidentError("the agent returned no session id")
            if cancel.is_set():
                raise TurnCancelled("cancelled before delivery")
            try:
                _check(req.check_cancelled)
            except BaseException as callback_error:
                raise _PropagateCallbackError(callback_error) from None
            _delivery(delivery, "not_sent", session_id, "", None)
            _delivery(delivery, "unknown", session_id, "", "session/prompt write pending")
            sent = True
            sent_at = time.monotonic()
            prompt_id = worker.request("session/prompt", {
                "sessionId": session_id, "prompt": [{"type": "text", "text": req.prompt}],
            })
            state: dict[str, Any] = {"accepted": False, "first_text": None}

            def accept() -> None:
                if not state["accepted"]:
                    state["accepted"] = True
                    metrics["turn_accept_ms"] = (time.monotonic() - sent_at) * 1000
                    _delivery(delivery, "accepted", session_id, str(prompt_id), None)

            def handle(message: dict[str, Any], raw: str) -> Any:
                nonlocal events
                if message.get("id") == prompt_id and "method" not in message:
                    accept()
                    if "error" in message:
                        _delivery(delivery, "rejected", session_id, str(prompt_id), message["error"])
                        raise TurnRejected(_error_message(message["error"]))
                    result = message.get("result")
                    return result if isinstance(result, Mapping) else {}
                if message.get("method") != "session/update":
                    return None
                params = message.get("params")
                if not isinstance(params, Mapping) or params.get("sessionId") != session_id:
                    return None
                update = params.get("update")
                if not isinstance(update, Mapping):
                    return None
                accept()
                events += 1
                kind = update.get("sessionUpdate")
                # Message and thought chunks are the answer arriving, one per
                # token; capping them fails any long answer. The deadline bounds them.
                if events > _MAX_RETAINED_EVENTS and kind not in {
                        "agent_message_chunk", "agent_thought_chunk"}:
                    raise ResidentError("the agent exceeded the per-turn event limit")
                if req.on_event:
                    req.on_event(message)
                if kind == "agent_message_chunk":
                    content = update.get("content")
                    text = content.get("text") if isinstance(content, Mapping) else None
                    if isinstance(text, str):
                        parts.append(text)
                        if state["first_text"] is None:
                            state["first_text"] = (time.monotonic() - sent_at) * 1000
                            metrics["first_text_ms"] = state["first_text"]
                        if req.on_text:
                            req.on_text(text)
                elif kind in {"tool_call", "tool_call_update"} and req.on_action:
                    title = str(update.get("title") or update.get("kind") or "a tool")
                    if kind == "tool_call":
                        req.on_action(f"asked for {title}; Kriko grants the agent no tools")
                elif kind == "usage_update":
                    for key in ("used", "size"):
                        if isinstance(update.get(key), int):
                            usage[f"context_{key}"] = update[key]
                return None

            def interrupt() -> None:
                try:
                    worker.notify("session/cancel", {"sessionId": session_id})
                except Exception:
                    pass

            def stopped(message: dict[str, Any]) -> bool:
                return message.get("id") == prompt_id and "method" not in message

            result = pool.pump(worker, req, cancel, deadline, handle, interrupt, stopped, "the session")
            reason = str(result.get("stopReason") or "")
            reported = result.get("usage")
            if isinstance(reported, Mapping):
                usage.update({k: v for k, v in reported.items() if isinstance(v, (int, float))})
            if reason == "cancelled":
                raise TurnCancelled("the session was cancelled")
            if reason and reason != "end_turn":
                raise ResidentError(f"the agent stopped without finishing: {reason}")
            metrics["event_count"] = events
            self._close(worker, session_id)
            return ResidentResult("".join(parts).strip(), session_id, str(prompt_id), usage, {}, metrics)
        except _PropagateCallbackError as exc:
            raise exc.original
        except TurnRejected:
            worker.quarantined = True
            raise
        except TurnCancelled:
            raise
        except DeliveryUncertain:
            if sent:
                _delivery(delivery, "unknown", session_id, str(prompt_id or ""),
                          "delivery outcome could not be established")
            worker.quarantined = True
            raise
        except TimeoutError:
            worker.quarantined = True
            raise
        except ResidentError:
            worker.quarantined = True
            raise
        except BaseException as exc:
            if sent:
                _delivery(delivery, "unknown", session_id, str(prompt_id or ""), str(exc))
                worker.quarantined = True
                raise DeliveryUncertain(f"delivery became uncertain: {exc}") from exc
            raise TransportUnavailable(str(exc)) from exc

    @staticmethod
    def _close(worker: _Worker, session_id: str) -> None:
        """Let the agent free the finished session, where it says it can."""
        if worker.state.get("can_close"):
            try:
                worker.rpc("session/close", {"sessionId": session_id}, timeout=2.0)
            except BaseException:
                pass


# ── helpers ──────────────────────────────────────────────────────────────────


def _check(callback: Callable[[], None] | None) -> None:
    if callback:
        callback()


def _delivery(callback: DeliveryCallback | None, status: str, context_id: str, turn_id: str, detail: Any) -> None:
    if callback:
        callback(status, context_id, turn_id, detail)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("the request deadline expired")
    return remaining


def _fail(worker: _Worker, message: str) -> None:
    failure = CodexTransportError(message)
    try:
        worker.incoming.put_nowait(failure)
    except queue.Full:
        try:
            while True:
                worker.incoming.get_nowait()
        except queue.Empty:
            pass
        try:
            worker.incoming.put_nowait(failure)
        except queue.Full:
            pass


def _release(worker: _Worker) -> None:
    _terminate(worker.process, worker.job)
    worker.job = None
    if worker.resource_guard is not None:
        worker.resource_guard.__exit__(None, None, None)
        worker.resource_guard = None


# ── the shared pool and the folders it owns ──────────────────────────────────

_LOCK = threading.RLock()
_TRANSPORT: ResidentTransport | None = None
_FOLDERS: dict[str, tempfile.TemporaryDirectory] = {}


def owned_folder(key: str, prefix: str = "kriko-agent-") -> Path:
    """A private, empty folder that lives as long as the process, per key.

    A resident worker's working directory (and, for Vibe, its configuration
    home) must outlive one request, so it cannot be the per-request temporary
    folder the process adapter uses. The same key gets the same folder, which
    is what lets an identical profile find its worker again.
    """
    digest = hashlib.sha256(key.encode()).hexdigest()
    with _LOCK:
        folder = _FOLDERS.get(digest)
        if folder is None:
            folder = tempfile.TemporaryDirectory(prefix=prefix)
            os.chmod(folder.name, 0o700)
            _FOLDERS[digest] = folder
        return Path(folder.name)


def transport() -> ResidentTransport:
    global _TRANSPORT
    with _LOCK:
        if _TRANSPORT is None:
            _TRANSPORT = ResidentTransport()
        return _TRANSPORT


def release_idle() -> None:
    """Make room for another adapter without interrupting active research."""
    with _LOCK:
        owner = _TRANSPORT
    if owner is not None:
        owner.release_idle()


def shutdown() -> None:
    global _TRANSPORT
    with _LOCK:
        owner, _TRANSPORT = _TRANSPORT, None
    if owner is not None:
        owner.close()
    with _LOCK:
        folders = list(_FOLDERS.values())
        _FOLDERS.clear()
    for folder in folders:
        try:
            folder.cleanup()
        except OSError:
            pass


atexit.register(shutdown)
