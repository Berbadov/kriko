"""Resident, isolated NDJSON transport for Codex app-server.

Workers are reused only when their complete profile identity matches. Every
call creates a fresh Codex thread and a fresh turn, so research jobs never
inherit conversation state from each other.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections import deque
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from app.agentresources import slot
from app.processcontrol import close_process, contained_popen, create_job_object


class CodexTransportError(RuntimeError):
    """Base class for transport errors."""


class DeliveryUncertain(CodexTransportError):
    """The server may have received a turn request; callers must not replay it."""


class TransportUnavailable(CodexTransportError):
    """The app-server could not start or initialize before prompt delivery."""


class TurnRejected(CodexTransportError):
    """The app-server explicitly rejected a turn request."""


class TurnCancelled(CodexTransportError):
    """A requested cancellation stopped the active turn."""

    cancelled = True


class _PropagateCallbackError(Exception):
    def __init__(self, original: BaseException) -> None:
        self.original = original


@dataclass(frozen=True)
class CodexProfile:
    """Isolation and model settings for one reusable worker identity.

    ``home_dir`` is the isolated Codex home supplied by the caller. It must
    contain any intended account state and config. Ambient Codex settings are
    never read. ``env`` is an explicit allowlist of extra process variables.
    ``tool_grant`` is included in the profile identity and the prompt contract;
    unsupported tool grants are rejected instead of silently widening access.
    """

    executable: str
    home_dir: str
    cwd: str
    model: str = ""
    effort: str = ""
    env: Mapping[str, str] = field(default_factory=dict)
    tool_grant: tuple[str, ...] = ()
    app_server_args: tuple[str, ...] = ()
    # Pin identity to the account/config snapshot that created an owned home.
    # Codex may refresh auth.json and models_cache.json while a worker is live.
    account_fingerprint: str = ""
    config_fingerprint: str = ""

    def identity(self) -> str:
        executable = Path(self.executable).resolve()
        exe_stamp: tuple[str, int | None, int | None]
        try:
            stat = executable.stat()
            exe_stamp = (str(executable), stat.st_size, stat.st_mtime_ns)
        except OSError:
            exe_stamp = (str(executable), None, None)
        home = Path(self.home_dir).resolve()
        config_path = home / "config.toml"
        try:
            config_stamp = self.config_fingerprint or hashlib.sha256(config_path.read_bytes()).hexdigest()
        except OSError:
            config_stamp = self.config_fingerprint or "missing"
        if self.account_fingerprint or self.env.get("CODEX_ACCOUNT_ID", ""):
            account_stamp = self.account_fingerprint or self.env["CODEX_ACCOUNT_ID"]
        else:
            try:
                account_stamp = hashlib.sha256((home / "auth.json").read_bytes()).hexdigest()
            except OSError:
                account_stamp = "missing"
        payload = {
            "exe": exe_stamp,
            "home": str(home),
            "config_stamp": config_stamp,
            "cwd": str(Path(self.cwd).resolve()),
            "account": account_stamp,
            "env": sorted(self.env.items()),
            "model": self.model,
            "effort": self.effort,
            "tools": sorted(self.tool_grant),
            "args": self.app_server_args,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class CodexRequest:
    prompt: str
    output_schema: Mapping[str, Any] | None = None
    timeout: float = 300.0
    on_event: Callable[[Mapping[str, Any]], None] | None = None
    on_delivery: Callable[..., None] | None = None
    on_action: Callable[[Mapping[str, Any]], None] | None = None
    on_text: Callable[[str], None] | None = None
    check_cancelled: Callable[[], None] | None = None


@dataclass(frozen=True)
class CodexResult:
    text: str
    thread_id: str
    turn_id: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[Mapping[str, Any], ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class _Worker:
    profile: CodexProfile
    identity: str
    process: subprocess.Popen[str]
    incoming: queue.Queue[dict[str, Any] | BaseException]
    job: int | None = None
    worker_start_ms: float = 0.0
    handshake_ms: float = 0.0
    startup_queue_ms: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    next_id: int = 0
    last_request_id: str = ""
    last_used: float = field(default_factory=time.monotonic)
    busy: bool = False
    quarantined: bool = False
    thread: threading.Thread | None = None
    resource_guard: AbstractContextManager[None] | None = None

    def write_raw(self, value: Mapping[str, Any]) -> None:
        if self.process.stdin is None:
            raise CodexTransportError("Codex app-server stdin is unavailable")
        with self.write_lock:
            self.process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
            self.process.stdin.flush()

    def write_request(self, method: str, params: Mapping[str, Any]) -> str:
        self.next_id += 1
        request_id = str(self.next_id)
        self.last_request_id = request_id
        self.write_raw({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        return request_id

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self.write_raw({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def next_message(self, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            value = self.incoming.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(value, BaseException):
            raise CodexTransportError(str(value)) from value
        return value

    def rpc(self, method: str, params: Mapping[str, Any], timeout: float = 30) -> Mapping[str, Any]:
        request_id = self.write_request(method, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.next_message(timeout=max(0.01, min(0.1, deadline - time.monotonic())))
            if message is None or message.get("id") != request_id:
                continue
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


DeliveryCallback = Callable[..., None]
#: One protocol line carries a whole final answer (`turn/completed` holds the
#: agent message), so this cap is the largest answer the transport accepts. It
#: was 64 KiB, which failed any answer past roughly 16k tokens; it is now a
#: memory guard far above that.
_MAX_LINE_CHARS = 8 * 1024 * 1024
_MAX_BUFFERED_MESSAGES = 64
#: How many of a turn's events are kept for the caller to inspect. A bound on
#: memory only: a turn that streams more than this is a long answer, and is
#: not a failure.
_MAX_RETAINED_EVENTS = 256


class _EventLog:
    """The events of one turn: the most recent ones kept, and how many arrived.

    Every streamed token is an event, so the count is the length of the answer.
    It used to raise past 256, which failed each reply that streamed more than
    256 events a few seconds into the turn, recorded as DeliveryUncertain.
    """

    def __init__(self) -> None:
        self._recent: deque[Mapping[str, Any]] = deque(maxlen=_MAX_RETAINED_EVENTS)
        self.total = 0

    def append(self, event: Mapping[str, Any]) -> None:
        self.total += 1
        self._recent.append(event)

    def __len__(self) -> int:
        return self.total

    def snapshot(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._recent)


class CodexTransport:
    """Thread-safe pool of resident Codex app-server workers."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        idle_seconds: float = 900,
        low_memory_idle_seconds: float = 120,
        max_warm_workers: int | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self.executable = executable
        self.idle_seconds = idle_seconds
        self.low_memory_idle_seconds = low_memory_idle_seconds
        self.max_warm_workers = max_warm_workers or (1 if _total_memory_gib() <= 8 else 4)
        self._popen = popen
        self._workers: list[_Worker] = []
        self._lock = threading.RLock()
        self._available = threading.Condition(self._lock)
        self._starting = 0
        self.max_workers = _agent_child_limit()
        self._closed = False
        self._reaper_stop = threading.Event()
        self._reaper = threading.Thread(target=self._reap_loop, name="codex-worker-reaper", daemon=True)
        self._reaper.start()

    def run(
        self,
        profile: CodexProfile | Mapping[str, Any],
        request: CodexRequest | Mapping[str, Any],
        *,
        cancel_event: threading.Event | None = None,
        on_event: Callable[[Mapping[str, Any]], None] | None = None,
        on_delivery: DeliveryCallback | None = None,
        on_action: Callable[[Mapping[str, Any]], None] | None = None,
        on_text: Callable[[str], None] | None = None,
        check_cancelled: Callable[[], None] | None = None,
    ) -> CodexResult:
        """Run one independent research job using the supplied isolated profile."""
        run_started = time.monotonic()
        prof = _profile(profile, self.executable)
        req = _request(request, on_event, on_delivery, on_action, on_text, check_cancelled)
        if not req.prompt.strip():
            raise ValueError("prompt must not be empty")
        if req.output_schema is not None and not isinstance(req.output_schema, Mapping):
            raise ValueError("output_schema must be a JSON object")
        if prof.tool_grant:
            raise ValueError("Codex transport does not grant dynamic tools")
        if prof.app_server_args:
            raise ValueError("custom app-server arguments are not allowed")
        cancel = cancel_event or threading.Event()
        def check_before_spawn() -> None:
            if cancel.is_set():
                raise TurnCancelled("cancelled before Codex worker start")
            try:
                _check_cancelled(req.check_cancelled)
            except BaseException as exc:
                raise _PropagateCallbackError(exc) from None
        _delivery(req.on_delivery, "not_sent", "", "", None)
        deadline = run_started + req.timeout
        try:
            acquisition = self._acquire(prof, check_before_spawn, deadline)
            worker = acquisition.worker
        except _PropagateCallbackError as exc:
            raise exc.original
        except TurnCancelled:
            raise
        try:
            with worker.lock:
                if cancel.is_set():
                    raise TurnCancelled("cancelled before turn delivery")
                worker.busy = True
                worker.last_used = time.monotonic()
                metrics = {
                    "queue_ms": acquisition.queue_ms + (worker.startup_queue_ms if not acquisition.reused else 0.0),
                    "worker_start_ms": 0.0 if acquisition.reused else worker.worker_start_ms,
                    "handshake_ms": 0.0 if acquisition.reused else worker.handshake_ms,
                    "reused_worker": acquisition.reused,
                }
                return self._run_turn(worker, req, cancel, deadline, run_started, metrics)
        finally:
            with self._lock:
                worker.busy = False
                worker.last_used = time.monotonic()
                if worker.quarantined or self._closed:
                    self._discard_locked(worker)
                self._available.notify_all()

    def close(self, *, wait: bool = True) -> None:
        """Stop workers and the idle reaper. Safe to call more than once."""
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
        """Release idle workers so other providers can acquire child slots.

        Workers are detached while holding the pool lock, then terminated and
        their host permits released after unlocking. Starting and busy workers
        remain owned by their current operation.
        """
        with self._available:
            idle = [worker for worker in self._workers if not worker.busy]
            if limit is not None:
                idle = idle[:max(0, limit)]
            for worker in idle:
                self._workers.remove(worker)
            if idle:
                self._available.notify_all()
        for worker in idle:
            _terminate(worker.process, worker.job)
            worker.job = None
            if worker.resource_guard is not None:
                worker.resource_guard.__exit__(None, None, None)
                worker.resource_guard = None
        return len(idle)

    def _acquire(
        self, profile: CodexProfile, check: Callable[[], None] | None = None,
        deadline: float | None = None,
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
                    if worker.identity == identity and not worker.busy and not worker.quarantined and worker.process.poll() is None:
                        worker.busy = True
                        return _Acquisition(worker, True, (time.monotonic() - requested_at) * 1000)
                evict = next((w for w in self._workers if not w.busy), None)
                if evict is not None:
                    self._workers.remove(evict)
                elif len(self._workers) + self._starting < self.max_workers:
                    self._starting += 1
                    break
                else:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("timed out waiting for an idle Codex worker")
                    self._available.wait(min(0.05, remaining) if remaining is not None else 0.05)
                    continue
            if evict is not None:
                _terminate(evict.process, evict.job)
                evict.job = None
                if evict.resource_guard is not None:
                    evict.resource_guard.__exit__(None, None, None)
                    evict.resource_guard = None
        try:
            queue_ms = (time.monotonic() - requested_at) * 1000
            worker = self._start_worker(profile, identity, check, deadline)
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
        self, profile: CodexProfile, identity: str, check: Callable[[], None] | None = None,
        deadline: float | None = None,
    ) -> _Worker:
        exe = self.executable or profile.executable
        if not exe or not Path(exe).is_file():
            raise TransportUnavailable("Codex executable is unavailable")
        home = Path(profile.home_dir).resolve()
        cwd = Path(profile.cwd).resolve()
        if not home.is_absolute() or not cwd.is_dir():
            raise CodexTransportError("Codex profile home and working directory must be valid absolute paths")
        env = _isolated_env(profile, home)
        command = [exe, "app-server", "--stdio", "--strict-config", "--disable", "shell_tool", "--disable", "web_search_request", "--disable", "multi_agent", "-c", 'approval_policy="never"', "-c", 'web_search="disabled"']
        remaining = None if deadline is None else max(0, deadline - time.monotonic())
        resource_guard = slot("agent_child", key=identity, check=check, timeout=remaining)
        wait_started = time.monotonic()
        resource_guard.__enter__()
        startup_queue_ms = (time.monotonic() - wait_started) * 1000
        job: int | None = None
        try:
            job = create_job_object() if self._popen is subprocess.Popen else None
            spawn_started = time.monotonic()
            process = contained_popen(
                command,
                factory=self._popen,
                job=job,
                resource_kind=None,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except BaseException as exc:
            resource_guard.__exit__(None, None, None)
            _close_job(job)
            if isinstance(exc, (TimeoutError, TurnCancelled, _PropagateCallbackError)):
                raise
            raise TransportUnavailable(f"could not start Codex app-server: {exc}") from exc
        incoming: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=_MAX_BUFFERED_MESSAGES)
        worker = _Worker(
            profile, identity, process, incoming, job=job,
            worker_start_ms=(time.monotonic() - spawn_started) * 1000,
            startup_queue_ms=startup_queue_ms,
        )
        worker.resource_guard = resource_guard
        worker.thread = threading.Thread(target=self._read_loop, args=(worker,), name="codex-app-server-reader", daemon=True)
        try:
            worker.thread.start()
        except BaseException as exc:
            _terminate(process, job)
            worker.job = None
            resource_guard.__exit__(None, None, None)
            raise TransportUnavailable(f"could not start Codex protocol reader: {exc}") from exc
        handshake_started = time.monotonic()
        try:
            remaining = 20.0 if deadline is None else min(20.0, max(0.0, deadline - time.monotonic()))
            worker.rpc("initialize", {
                "clientInfo": {"name": "kriko", "title": "Kriko research", "version": "1.6.2"},
                "capabilities": {"experimentalApi": False},
            }, timeout=remaining)
            worker.notify("initialized", {})
            worker.handshake_ms = (time.monotonic() - handshake_started) * 1000
        except TimeoutError:
            _terminate(process, job)
            worker.job = None
            resource_guard.__exit__(None, None, None)
            raise
        except BaseException as exc:
            _terminate(process, job)
            worker.job = None
            resource_guard.__exit__(None, None, None)
            raise TransportUnavailable(f"Codex app-server initialization failed: {exc}") from exc
        return worker

    def _run_turn(
        self, worker: _Worker, req: CodexRequest, cancel: threading.Event, deadline: float,
        run_started: float, metrics: dict[str, Any],
    ) -> CodexResult:
        profile = worker.profile
        delivery = req.on_delivery
        thread_id = ""
        turn_id = ""
        sent = False
        events = _EventLog()
        usage: dict[str, Any] = {}
        try:
            if cancel.is_set():
                raise TurnCancelled("cancelled before thread start")
            try:
                _check_cancelled(req.check_cancelled)
            except BaseException as callback_error:
                raise _PropagateCallbackError(callback_error) from None
            thread_started = time.monotonic()
            thread = worker.rpc("thread/start", {
                "cwd": str(Path(profile.cwd).resolve()),
                "model": profile.model or None,
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "ephemeral": True,
                "config": {
                    "approval_policy": "never",
                    "web_search": "disabled",
                    "features": {"shell_tool": False, "web_search_request": False, "multi_agent": False},
                    "mcp_servers": {},
                },
            }, timeout=_remaining(deadline))
            metrics["thread_start_ms"] = (time.monotonic() - thread_started) * 1000
            thread_id = _nested_id(thread, "threadId", "thread")
            if not thread_id:
                raise CodexTransportError("Codex app-server returned no thread ID")
            if cancel.is_set():
                raise TurnCancelled("cancelled before turn delivery")
            try:
                _check_cancelled(req.check_cancelled)
            except BaseException as callback_error:
                raise _PropagateCallbackError(callback_error) from None
            _remaining(deadline)
            params: dict[str, Any] = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": req.prompt}],
                "cwd": str(Path(profile.cwd).resolve()),
                "sandboxPolicy": {"type": "readOnly"},
                "approvalPolicy": "never",
            }
            if profile.model:
                params["model"] = profile.model
            if profile.effort:
                params["effort"] = profile.effort
            if req.output_schema:
                params["outputSchema"] = dict(req.output_schema)
            _delivery(delivery, "not_sent", thread_id, "", None)
            _delivery(delivery, "unknown", thread_id, "", "turn/start write pending")
            sent = True
            turn_sent_at = time.monotonic()
            worker.write_request("turn/start", params)
            first_text_ms: float | None = None
            turn_response: dict[str, Any] | None = None
            while turn_response is None:
                if cancel.is_set():
                    self._interrupt(worker, thread_id, turn_id)
                    if turn_id:
                        stopped = self._wait_turn_stop(worker, thread_id, turn_id, 2.0, events, usage, req.on_event)
                        worker.quarantined = not stopped
                    else:
                        worker.quarantined = True
                    raise TurnCancelled("cancelled while waiting for turn start")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DeliveryUncertain("timed out awaiting turn/start response")
                try:
                    _check_cancelled(req.check_cancelled)
                except BaseException as callback_error:
                    self._interrupt(worker, thread_id, turn_id)
                    worker.quarantined = True
                    raise _PropagateCallbackError(callback_error) from None
                message = worker.next_message(timeout=min(0.1, remaining))
                if message is None:
                    continue
                if "id" in message and message.get("id") == worker.last_request_id:
                    if "error" in message:
                        _delivery(delivery, "rejected", thread_id, "", message["error"])
                        raise TurnRejected(_error_message(message["error"]))
                    turn_response = message.get("result", {})
                    turn_id = _nested_id(turn_response, "turnId", "turn")
                    if not turn_id:
                        raise DeliveryUncertain("turn/start response contained no turn ID")
                    _delivery(delivery, "accepted", thread_id, turn_id, None)
                    metrics["turn_accept_ms"] = (time.monotonic() - turn_sent_at) * 1000
                    break
                event = _route_event(message, thread_id, turn_id)
                if event is None:
                    continue
                if event.get("method") == "turn/started":
                    turn_id = str(_params(event).get("turn", {}).get("id") or "")
                if _is_text_delta(event) and first_text_ms is None:
                    first_text_ms = (time.monotonic() - turn_sent_at) * 1000
                    metrics["first_text_ms"] = first_text_ms
                _handle_event(event, thread_id, turn_id, events, usage, req.on_event, req.on_action, req.on_text)
            while True:
                try:
                    _check_cancelled(req.check_cancelled)
                except BaseException as callback_error:
                    self._interrupt(worker, thread_id, turn_id)
                    stopped = self._wait_turn_stop(worker, thread_id, turn_id, 2.0, events, usage, req.on_event)
                    worker.quarantined = not stopped
                    raise _PropagateCallbackError(callback_error) from None
                if cancel.is_set():
                    self._interrupt(worker, thread_id, turn_id)
                    stopped = self._wait_turn_stop(worker, thread_id, turn_id, 2.0, events, usage, req.on_event)
                    worker.quarantined = not stopped
                    if stopped:
                        raise TurnCancelled("Codex turn cancelled")
                    raise TurnCancelled("Codex turn did not stop; worker quarantined")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._interrupt(worker, thread_id, turn_id)
                    worker.quarantined = True
                    raise DeliveryUncertain("Codex turn timed out; worker quarantined")
                message = worker.next_message(timeout=min(0.1, remaining))
                if message is None:
                    continue
                if "id" in message and message.get("id") == worker.last_request_id:
                    continue
                event = _route_event(message, thread_id, turn_id)
                if event is None:
                    continue
                if event.get("method") == "turn/started":
                    observed = str(_params(event).get("turn", {}).get("id") or "")
                    if observed:
                        turn_id = observed
                if _is_text_delta(event) and first_text_ms is None:
                    first_text_ms = (time.monotonic() - turn_sent_at) * 1000
                    metrics["first_text_ms"] = first_text_ms
                done = _handle_event(event, thread_id, turn_id, events, usage, req.on_event, req.on_action, req.on_text)
                if done is not None:
                    if done.get("status") != "completed":
                        raise CodexTransportError(_error_message(done.get("error") or done.get("status")))
                    text = _final_text(done)
                    thread_data = thread.get("thread", {}) if isinstance(thread, Mapping) else {}
                    actual_model = thread.get("model") if isinstance(thread, Mapping) else None
                    if not actual_model and isinstance(thread_data, Mapping):
                        actual_model = thread_data.get("model")
                    metrics.update({
                        "event_count": len(events), "model": actual_model or profile.model,
                        "total_ms": (time.monotonic() - run_started) * 1000,
                        "first_text_ms": first_text_ms,
                    })
                    return CodexResult(text, thread_id, turn_id, usage, events.snapshot(), metrics)
        except _PropagateCallbackError as exc:
            raise exc.original
        except TurnRejected:
            worker.quarantined = True
            raise
        except TurnCancelled:
            raise
        except DeliveryUncertain:
            if sent:
                _delivery(delivery, "unknown", thread_id, turn_id, "delivery outcome could not be established")
            worker.quarantined = True
            raise
        except TimeoutError:
            worker.quarantined = True
            raise
        except BaseException as exc:
            if sent:
                _delivery(delivery, "unknown", thread_id, turn_id, str(exc))
                worker.quarantined = True
                raise DeliveryUncertain(f"Codex delivery became uncertain: {exc}") from exc
            raise TransportUnavailable(str(exc)) from exc

    def _interrupt(self, worker: _Worker, thread_id: str, turn_id: str) -> None:
        if thread_id and turn_id:
            try:
                worker.notify("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
            except Exception:
                pass

    def _wait_turn_stop(
        self, worker: _Worker, thread_id: str, turn_id: str, seconds: float,
        events: _EventLog, usage: dict[str, Any], callback: Callable[[Mapping[str, Any]], None] | None,
    ) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            message = worker.next_message(timeout=min(0.1, deadline - time.monotonic()))
            if message is None:
                continue
            event = _route_event(message, thread_id, turn_id)
            if event is not None and _handle_event(event, thread_id, turn_id, events, usage, callback) is not None:
                return True
        return False

    def _read_loop(self, worker: _Worker) -> None:
        assert worker.process.stdout is not None
        try:
            while True:
                line = worker.process.stdout.readline(_MAX_LINE_CHARS + 1)
                if not line:
                    break
                if len(line) > _MAX_LINE_CHARS:
                    _queue_failure(worker, "Codex app-server message exceeds the 64 KiB limit")
                    _terminate(worker.process, worker.job)
                    worker.job = None
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    _queue_failure(worker, f"invalid app-server JSON: {exc}")
                    continue
                if not isinstance(message, dict):
                    continue
                if "method" in message and "id" in message:
                    # app-server asks the client to perform a capability; Kriko
                    # grants no shell, file mutation, MCP, or unlisted tool.
                    response = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32000, "message": "client capability denied"}}
                    try:
                        worker.write_raw(response)
                    except Exception:
                        pass
                    continue
                if "id" in message:
                    _queue_message(worker, message)
                    continue
                _queue_message(worker, message)
        except BaseException as exc:
            _queue_failure(worker, str(exc))
        finally:
            _queue_failure(worker, "Codex app-server exited")

    def _reap_loop(self) -> None:
        while not self._reaper_stop.wait(15):
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
            evict = {id(worker): worker for worker in exited + aged + lru[:excess]}
            for worker in evict.values():
                self._discard_locked(worker)
            self._available.notify_all()

    def _discard_locked(self, worker: _Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        _terminate(worker.process, worker.job)
        worker.job = None
        if worker.resource_guard is not None:
            worker.resource_guard.__exit__(None, None, None)
            worker.resource_guard = None


def run(
    profile: CodexProfile | Mapping[str, Any],
    request: CodexRequest | Mapping[str, Any],
    *,
    cancel_event: threading.Event | None = None,
    transport: CodexTransport | None = None,
    on_event: Callable[[Mapping[str, Any]], None] | None = None,
    on_delivery: DeliveryCallback | None = None,
    on_action: Callable[[Mapping[str, Any]], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> CodexResult:
    """Convenience entry point; pass a shared transport to enable persistence."""
    owner = transport or CodexTransport()
    try:
        return owner.run(profile, request, cancel_event=cancel_event, on_event=on_event, on_delivery=on_delivery,
                         on_action=on_action, on_text=on_text, check_cancelled=check_cancelled)
    finally:
        if transport is None:
            owner.close()


def _profile(value: CodexProfile | Mapping[str, Any], default_executable: str | None) -> CodexProfile:
    if isinstance(value, CodexProfile):
        return value
    data = dict(value)
    aliases = {"exe_path": "executable", "home": "home_dir", "environment": "env", "tools": "tool_grant"}
    for old, new in aliases.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
    data.setdefault("executable", default_executable or shutil.which("codex") or "")
    data["tool_grant"] = tuple(data.get("tool_grant", ()))
    data["app_server_args"] = tuple(data.get("app_server_args", ()))
    return CodexProfile(**data)


def _request(
    value: CodexRequest | Mapping[str, Any],
    event_callback: Callable[[Mapping[str, Any]], None] | None,
    delivery_callback: DeliveryCallback | None,
    action_callback: Callable[[Mapping[str, Any]], None] | None,
    text_callback: Callable[[str], None] | None,
    cancel_callback: Callable[[], None] | None,
) -> CodexRequest:
    if isinstance(value, CodexRequest):
        return CodexRequest(value.prompt, value.output_schema, value.timeout,
                            event_callback or value.on_event, delivery_callback or value.on_delivery,
                            action_callback or value.on_action, text_callback or value.on_text,
                            cancel_callback or value.check_cancelled)
    data = dict(value)
    if "schema" in data and "output_schema" not in data:
        data["output_schema"] = data.pop("schema")
    if "timeout_seconds" in data and "timeout" not in data:
        data["timeout"] = data.pop("timeout_seconds")
    data["on_event"] = event_callback or data.get("on_event")
    data["on_delivery"] = delivery_callback or data.get("on_delivery")
    data["on_action"] = action_callback or data.get("on_action")
    data["on_text"] = text_callback or data.get("on_text")
    data["check_cancelled"] = cancel_callback or data.get("check_cancelled")
    return CodexRequest(**data)


def _isolated_env(profile: CodexProfile, home: Path) -> dict[str, str]:
    safe_names = ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramData")
    env = {name: os.environ[name] for name in safe_names if name in os.environ}
    env.update({str(k): str(v) for k, v in profile.env.items()})
    env["CODEX_HOME"] = str(home)
    env["HOME"] = str(home)
    if os.name == "nt":
        env["USERPROFILE"] = str(home)
        env["APPDATA"] = str(home / "AppData" / "Roaming")
        env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    return env


def _nested_id(value: Any, key: str, child: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    candidate = value.get(key)
    if not candidate and isinstance(value.get(child), Mapping):
        candidate = value[child].get("id")
    return str(candidate or "")


def _params(message: Mapping[str, Any]) -> Mapping[str, Any]:
    value = message.get("params", {})
    return value if isinstance(value, Mapping) else {}


def _route_event(message: Mapping[str, Any], thread_id: str, turn_id: str) -> Mapping[str, Any] | None:
    if "method" not in message:
        return None
    params = _params(message)
    if params.get("threadId") != thread_id:
        return None
    turn = params.get("turn")
    observed_turn = params.get("turnId") or (turn.get("id") if isinstance(turn, Mapping) else None)
    if not turn_id and message.get("method") != "turn/started":
        return None
    if message.get("method") == "turn/started" and isinstance(turn, Mapping):
        observed_turn = turn.get("id")
    if turn_id and observed_turn != turn_id:
        return None
    if not observed_turn:
        return None
    return message


def _handle_event(
    event: Mapping[str, Any], thread_id: str, turn_id: str,
    events: _EventLog, usage: dict[str, Any], callback: Callable[[Mapping[str, Any]], None] | None,
    action_callback: Callable[[Mapping[str, Any]], None] | None = None,
    text_callback: Callable[[str], None] | None = None,
) -> Mapping[str, Any] | None:
    params = _params(event)
    if params.get("threadId") != thread_id:
        return None
    event_turn = params.get("turnId")
    if event_turn and turn_id and event_turn != turn_id:
        return None
    method = event.get("method")
    if method == "thread/tokenUsage/updated":
        token_usage = params.get("tokenUsage", {})
        if isinstance(token_usage, Mapping):
            usage.update(token_usage)
    # Command execution and file edits imply an attempted out-of-grant action.
    if method in {"item/started", "item/completed"}:
        item = params.get("item", {})
        if isinstance(item, Mapping) and item.get("type") in {"commandExecution", "fileChange", "mcpToolCall"}:
            raise CodexTransportError(f"Codex requested denied capability: {item.get('type')}")
    events.append(event)
    if callback:
        callback(event)
    if action_callback:
        action_callback(event)
    if method in {"item/agentMessage/delta", "agentMessage/delta"} and text_callback:
        delta = params.get("delta")
        if isinstance(delta, str):
            text_callback(delta)
    if method == "turn/completed":
        turn = params.get("turn", {})
        if isinstance(turn, Mapping):
            usage.update(turn.get("usage", {}) if isinstance(turn.get("usage"), Mapping) else {})
            return turn
    return None


def _final_text(turn: Mapping[str, Any]) -> str:
    messages: list[tuple[Any, str]] = []
    for item in turn.get("items", ()):
        if not isinstance(item, Mapping):
            continue
        if item.get("type") in {"agentMessage", "assistantMessage"}:
            text = item.get("text")
            if isinstance(text, str):
                messages.append((item.get("phase"), text))

    # A turn can contain commentary and partial-answer messages before its
    # actual answer.  In particular, concatenating those messages corrupts
    # structured output (for example, a JSON schema response).  Prefer the
    # explicit final phase whenever the server supplies one.
    finals = [text for phase, text in messages if phase == "final_answer"]
    if finals:
        return "\n".join(finals).strip()

    # Older app-server versions omitted phase metadata.  Preserve their
    # behavior for those messages while ignoring explicitly non-final and
    # unknown phases, which must never displace a known final answer.
    legacy = [text for phase, text in messages if phase is None]
    return "\n".join(legacy).strip()


def _delivery(callback: DeliveryCallback | None, status: str, context_id: str, turn_id: str, detail: Any) -> None:
    if callback:
        callback(status, context_id, turn_id, detail)


def _check_cancelled(callback: Callable[[], None] | None) -> None:
    if callback:
        callback()


def _queue_message(worker: _Worker, value: dict[str, Any]) -> None:
    """Hand a message to the consumer, waiting for it if it is busy.

    A full queue means the consumer is slower than a burst of output (a
    progress write, a log line), which is not a fault in the server. The
    failure used to kill the worker, so a long answer died as soon as it
    out-ran the consumer by 64 lines. The server's own pipe is the flow
    control: the reader waits, and gives up only when the process has exited,
    since then nothing will read the queue again.
    """
    while True:
        try:
            worker.incoming.put(value, timeout=0.2)
            return
        except queue.Full:
            if worker.process.poll() is not None:
                return


def _queue_failure(worker: _Worker, message: str) -> None:
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


def _error_message(error: Any) -> str:
    if isinstance(error, Mapping):
        return str(error.get("message") or error)
    return str(error or "Codex turn failed")


def _total_memory_gib() -> float:
    from app.agentresources import total_memory_gib

    return total_memory_gib()


def _agent_child_limit() -> int:
    profiles = {"quiet": 1, "balanced": 2, "fast": 4}
    profile = os.environ.get("KRIKO_RESOURCE_PROFILE", "balanced").strip().lower()
    default = profiles.get(profile, 2)
    try:
        value = int(os.environ.get("KRIKO_MAX_AGENT_CHILDREN", default))
    except (TypeError, ValueError):
        value = default
    return min(16, max(1, value))


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Codex request deadline expired")
    return remaining


def _is_text_delta(event: Mapping[str, Any]) -> bool:
    return event.get("method") in {"item/agentMessage/delta", "agentMessage/delta"}


def _close_job(job: int | None) -> None:
    if job is None or os.name != "nt":
        return
    import ctypes as _ctypes
    ctypes: Any = _ctypes  # Windows-only attributes; the Linux type stubs lack them

    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)


def _terminate(process: subprocess.Popen[str], job: int | None = None) -> None:
    try:
        close_process(process, job)
    except Exception:
        _close_job(job)
        if process.poll() is not None:
            return
        try:
            process.kill()
        except Exception:
            pass
