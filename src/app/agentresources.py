"""Host-wide limits shared by every concurrent research job.

The limiter lives at module scope deliberately: a per-job semaphore multiplies
the allowed load as jobs are added. Waiting checks cancellation frequently,
preserves ordering for each source, and lets an eligible different source pass
a caller blocked on one saturated source.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator

_PROFILES = {"quiet": 1, "balanced": 2, "fast": 4}


def _bounded_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return min(high, max(low, value))


def _profile() -> str:
    value = os.environ.get("KRIKO_RESOURCE_PROFILE", "balanced").strip().lower()
    return value if value in _PROFILES else "balanced"


#: How many runs the reader asked to have going at once (Settings → Runs). The
#: job runner hands it in at every start. Before this, the agent-child budget
#: was the profile's number alone, so a reader who chose four runs got two
#: agent processes, and the other two sat waiting while their jobs said
#: "running" (the bug #133's reader hit). The profile stays the floor, so one
#: run beside a chat keeps today's two children; an operator's explicit
#: KRIKO_MAX_AGENT_CHILDREN is exact and is never raised.
_CHILD_FLOOR = 0


def set_agent_children_floor(runs: int) -> None:
    """The reader's run choice, as the least agent children that may run at once."""
    global _CHILD_FLOOR
    with _LIMITER.condition:
        _CHILD_FLOOR = max(0, min(16, int(runs)))
        _LIMITER.condition.notify_all()


def agent_child_limit() -> int:
    """How many agent processes may run on this host at once, right now."""
    return _LIMITER.limits("agent_child")[0]


def _agent_child_budget(profile: int) -> int:
    if os.environ.get("KRIKO_MAX_AGENT_CHILDREN", "").strip():
        return _bounded_env("KRIKO_MAX_AGENT_CHILDREN", profile, 1, 16)
    return max(profile, _CHILD_FLOOR)


class _Limiter:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.waiters: dict[str, deque[tuple[object, str]]] = {}
        self.used: dict[str, int] = {}
        self.sources: dict[tuple[str, str], int] = {}
        self.next_source: dict[str, float] = {}

    def limits(self, kind: str) -> tuple[int, int]:
        profile = _PROFILES[_profile()]
        if kind in {"cli", "agent_child"}:
            total = _agent_child_budget(profile)
            return total, total
        if kind in {"outbound", "network"}:
            total = _bounded_env("KRIKO_MAX_OUTBOUND", max(4, profile * 4), 1, 64)
            per_source = _bounded_env("KRIKO_MAX_PER_SOURCE", 2, 1, 16)
            return total, per_source
        if kind in {"probe", "cli_probe"}:
            return _bounded_env("KRIKO_MAX_PROBES", profile, 1, 16), 1
        if kind in {"inference", "local_inference"}:
            return _bounded_env("KRIKO_MAX_LOCAL_INFERENCE", 1, 1, 8), 1
        raise ValueError(f"unknown resource kind: {kind}")

    def acquire(self, kind: str, key: str, check: Callable[[], object] | None,
                timeout: float | None) -> None:
        group = ("outbound" if kind in {"outbound", "network"}
                 else "cli" if kind in {"cli", "agent_child"}
                 else "probe" if kind in {"probe", "cli_probe"}
                 else "inference")
        source_id = (group, key)
        ticket = object()
        began = time.monotonic()
        with self.condition:
            queue = self.waiters.setdefault(group, deque())
            entry = (ticket, key)
            queue.append(entry)
        try:
            while True:
                # A cancellation check can read SQLite and block behind a
                # writer. Never run caller code under the host-wide limiter
                # lock: one slow job must not stop unrelated permits releasing
                # or being acquired.
                if check is not None:
                    check()
                with self.condition:
                    # Read again on every pass: the reader may raise the run
                    # choice while this caller is already waiting for a slot.
                    total, per_source = self.limits(kind)
                    # A full per-source bucket must not stall unrelated hosts.
                    # Still keep callers for one source in arrival order, so a
                    # later request cannot overtake an earlier one for it.
                    earlier_same_source = False
                    for queued_ticket, queued_key in queue:
                        if queued_ticket is ticket:
                            break
                        if queued_key == key:
                            earlier_same_source = True
                            break
                    if (not earlier_same_source and self.used.get(group, 0) < total
                            and (not key or self.sources.get(source_id, 0) < per_source)):
                        queue.remove(entry)
                        self.used[group] = self.used.get(group, 0) + 1
                        if key:
                            self.sources[source_id] = self.sources.get(source_id, 0) + 1
                        return
                    if timeout is not None:
                        left = timeout - (time.monotonic() - began)
                        if left <= 0:
                            raise TimeoutError(f"timed out waiting for {kind} permit")
                        self.condition.wait(min(left, 0.05))
                    else:
                        self.condition.wait(0.05)
        except BaseException:
            with self.condition:
                queue.remove(entry)
                self.condition.notify_all()
            raise

    def release(self, kind: str, key: str) -> None:
        group = ("outbound" if kind in {"outbound", "network"}
                 else "cli" if kind in {"cli", "agent_child"}
                 else "probe" if kind in {"probe", "cli_probe"}
                 else "inference")
        with self.condition:
            self.used[group] -= 1
            if key:
                source_id = (group, key)
                left = self.sources.get(source_id, 1) - 1
                if left:
                    self.sources[source_id] = left
                else:
                    self.sources.pop(source_id, None)
            self.condition.notify_all()

    def pace(self, source: str, interval: float,
             check: Callable[[], object] | None = None) -> None:
        """Wait for this source's next monotonic start time across all jobs."""
        if not source or interval <= 0:
            return
        while True:
            # Same rule as acquire(): checks may reach outside this lock.
            if check is not None:
                check()
            with self.condition:
                now = time.monotonic()
                ready = self.next_source.get(source, now)
                delay = ready - now
                if delay <= 0:
                    self.next_source[source] = now + interval
                    if len(self.next_source) > 2048:
                        self.next_source = {
                            name: stamp for name, stamp in self.next_source.items()
                            if stamp > now
                        }
                    return
                self.condition.wait(min(delay, 0.05))


_LIMITER = _Limiter()


@contextlib.contextmanager
def slot(kind: str, key: str = "", check: Callable[[], object] | None = None,
         timeout: float | None = None) -> Iterator[None]:
    """Acquire a shared host permit; `check` is polled while waiting."""
    _LIMITER.acquire(kind, key, check, timeout)
    try:
        yield
    finally:
        _LIMITER.release(kind, key)


def pace(source: str, interval: float,
         check: Callable[[], object] | None = None) -> None:
    _LIMITER.pace(source, interval, check)


def memory_snapshot() -> tuple[int, int] | None:
    """Return total and currently available physical memory in bytes.

    Uses Windows' GlobalMemoryStatusEx or POSIX sysconf, with no optional
    package dependency. `None` means the platform could not report both.
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            query = kernel32.GlobalMemoryStatusEx
            query.argtypes = [ctypes.POINTER(_MemoryStatus)]
            query.restype = wintypes.BOOL
            if query(ctypes.byref(status)):
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)
                if total > 0 and available >= 0:
                    return total, available
        except Exception:
            return None
        return None

    sysconf = getattr(os, "sysconf", None)
    if not callable(sysconf):
        return None
    try:
        total = int(sysconf("SC_PHYS_PAGES")) * int(sysconf("SC_PAGE_SIZE"))
        available = int(sysconf("SC_AVPHYS_PAGES")) * int(sysconf("SC_PAGE_SIZE"))
    except (OSError, TypeError, ValueError):
        return None
    return (total, available) if total > 0 and available >= 0 else None


def total_memory_gib() -> float:
    """Host physical RAM, conservatively treating unknown hosts as <=8 GiB."""
    snapshot = memory_snapshot()
    return snapshot[0] / (1024**3) if snapshot else 8.0


def idle_policy(*, ram_available_mb: int | None = None,
                pressure_mb: int = 2048) -> str:
    """Return release/keep policy for a local model based on available RAM."""
    if ram_available_mb is None:
        snapshot = memory_snapshot()
        ram_available_mb = int(snapshot[1] / (1024 * 1024)) if snapshot else 0
    pressure = _bounded_env("KRIKO_RAM_PRESSURE_MB", pressure_mb, 256, 65536)
    return "release" if ram_available_mb < pressure else "keep"
