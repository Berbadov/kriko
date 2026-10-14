"""Start children so cancellation can always reach the whole process tree."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Any

from app.agentresources import slot

_NATIVE_POPEN = subprocess.Popen


class _ContainedPopen(subprocess.Popen):
    """Popen that holds a shared worker permit until it exits."""

    def set_permit(self, permit: Any | None) -> None:
        self._resource_permit = permit
        self._resource_released = False

    def _release_permit(self) -> None:
        if not getattr(self, "_resource_released", True):
            self._resource_released = True
            if self._resource_permit is not None:
                self._resource_permit.__exit__(None, None, None)

    def poll(self):
        result = super().poll()
        if result is not None:
            self._release_permit()
        return result

    def wait(self, timeout=None):
        try:
            return super().wait(timeout=timeout)
        finally:
            if super().poll() is not None:
                self._release_permit()


def _thread_for_process(pid: int) -> int:
    """Find the suspended child's primary thread on Windows."""
    import ctypes
    from ctypes import wintypes

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                return int(entry.th32ThreadID)
            more = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    raise OSError("could not locate suspended child thread")


def _resume_windows(proc: subprocess.Popen[Any]) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    handle = kernel32.OpenThread(0x0002, False, _thread_for_process(proc.pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel32.ResumeThread(handle) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def _assign_windows_job(job: int | None, proc: subprocess.Popen[Any]) -> None:
    if job is None:
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    process_handle = getattr(proc, "_handle", None)
    if process_handle is None:
        raise OSError("the suspended child has no process handle")
    if not kernel32.AssignProcessToJobObject(job, int(process_handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def _watch_exit(proc: "_ContainedPopen") -> None:
    try:
        proc.wait()
    except (OSError, subprocess.SubprocessError):
        proc._release_permit()


def _watch_process(proc: "_ContainedPopen") -> None:
    threading.Thread(target=_watch_exit, args=(proc,),
                     name=f"kriko-child-{proc.pid}", daemon=True).start()


def create_job_object() -> int | None:
    """Create a Windows tree owner that kills descendants when closed."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                 ctypes.c_void_p, wintypes.DWORD]
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    return int(job)


def contained_popen(command: Any, *, job: int | None = None,
                    factory=subprocess.Popen, check=None,
                    resource_kind: str | None = "agent_child",
                    permit_timeout: float | None = None,
                    **kwargs: Any) -> subprocess.Popen[Any]:
    """Start a process in a killable tree, assigning its Windows job before run.

    Supplying `factory` keeps existing Popen fakes simple. Windows' standard
    library closes the primary thread handle before returning from Popen, so
    creation is suspended and the native thread is reopened/resumed only
    after Job Object assignment.
    """
    if factory is not _NATIVE_POPEN:
        if os.name != "nt":
            kwargs.setdefault("start_new_session", True)
        return factory(command, **kwargs)
    permit = (slot(resource_kind, check=check, timeout=permit_timeout)
              if resource_kind is not None else None)
    if permit is not None:
        permit.__enter__()
    process_factory = _ContainedPopen
    if os.name != "nt":
        kwargs.setdefault("start_new_session", True)
        try:
            proc = process_factory(command, **kwargs)
            proc.set_permit(permit)
            _watch_process(proc)
            return proc
        except BaseException:
            if permit is not None:
                permit.__exit__(None, None, None)
            raise
    flags = int(kwargs.pop("creationflags", 0))
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    flags |= getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
    kwargs["creationflags"] = flags
    try:
        proc = process_factory(command, **kwargs)
    except BaseException:
        if permit is not None:
            permit.__exit__(None, None, None)
        raise
    proc.set_permit(permit)
    try:
        _assign_windows_job(job, proc)
        _resume_windows(proc)
        _watch_process(proc)
    except BaseException:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        proc._release_permit()
        raise
    return proc


def kill_tree(proc: subprocess.Popen[Any], job: int | None = None) -> None:
    """Terminate a Windows job or a POSIX session and wait briefly."""
    if os.name == "nt":
        if job is not None:
            import ctypes
            ctypes.WinDLL("kernel32", use_last_error=True).TerminateJobObject(job, 1)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        try:
            killpg = getattr(os, "killpg", None)
            sigkill = getattr(signal, "SIGKILL", None)
            if killpg is None or sigkill is None:
                proc.kill()
            else:
                killpg(proc.pid, sigkill)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except OSError:
                pass
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def close_process(proc: subprocess.Popen[Any], job: int | None = None) -> None:
    """Close a process tree's lifetime, including already-orphaned descendants."""
    kill_tree(proc, job)
    if os.name == "nt" and job is not None:
        import ctypes
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)
