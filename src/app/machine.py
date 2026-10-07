"""What this computer is, and which local model runtimes it has installed.

The Local LLM screen sizes a model against the GPU and tells the reader what
is missing, so it needs the machine's own numbers. Every field is asked of the
machine and left `None` where the machine does not say: a guessed VRAM figure
would size a download wrongly, which is worse than showing a dash.

No model, runtime version or size lives here. The three runtimes are the same
small closed vocabulary `providers/local_discovery.py` already names (programs
this app can talk to), and where each one lives is a fact about the install,
looked up and never assumed.

The answer is cached for a minute. Asking costs a subprocess (`nvidia-smi`) and
a few stat calls, the screen asks on every visit, and none of it changes at
the pace a reader navigates.
"""

import ctypes
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

CACHE_SECONDS = 60.0
SMI_TIMEOUT = 5.0

_lock = threading.Lock()
_cached: tuple[float, dict] | None = None


def _smi(run=subprocess.run) -> dict:
    """The first GPU's name and memory in MiB, or all `None`."""
    empty = {"name": None, "vram_total_mb": None, "vram_used_mb": None, "count": 0}
    exe = shutil.which("nvidia-smi")
    if not exe:
        return empty
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = run(
            [exe, "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=SMI_TIMEOUT, creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return empty
    if done.returncode != 0:
        return empty
    rows = [line for line in (done.stdout or "").splitlines() if line.strip()]
    if not rows:
        return empty
    name, _, rest = rows[0].partition(",")
    parts = [piece.strip() for piece in rest.split(",")]

    def mib(text: str) -> int | None:
        try:
            return int(float(text))
        except ValueError:
            return None  # "[N/A]" and the like: not measured

    return {
        "name": name.strip() or None,
        "vram_total_mb": mib(parts[0]) if len(parts) > 0 else None,
        "vram_used_mb": mib(parts[1]) if len(parts) > 1 else None,
        "count": len(rows),
    }


def _ram_total_mb() -> int | None:
    try:
        if os.name == "nt":
            class Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended", ctypes.c_ulonglong),
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined,unused-ignore]
                return None
            return int(status.total_phys // (1024 * 1024))
        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        pages = os.sysconf("SC_PHYS_PAGES")  # type: ignore[attr-defined,unused-ignore]
        size = os.sysconf("SC_PAGE_SIZE")  # type: ignore[attr-defined,unused-ignore]
        return int(pages * size // (1024 * 1024))
    except (OSError, ValueError, AttributeError):
        return None


def _cpu_name() -> str | None:
    try:
        if os.name == "nt":
            import winreg

            # The POSIX typeshed stub for `winreg` omits the Windows-only
            # symbols, even inside this runtime-guarded branch. Resolve them
            # dynamically so the cross-platform gate can type-check the
            # Windows implementation without changing its runtime behavior.
            open_key = getattr(winreg, "OpenKey", None)
            machine_key = getattr(winreg, "HKEY_LOCAL_MACHINE", None)
            query_value = getattr(winreg, "QueryValueEx", None)
            if not callable(open_key) or machine_key is None or not callable(query_value):
                return None
            with open_key(
                machine_key,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                name = str(query_value(key, "ProcessorNameString")[0]).strip()
                if name:
                    return name
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.is_file():
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.partition(":")[2].strip() or None
    except OSError:
        pass
    return platform.processor().strip() or None


#: Programs this app can serve a model through: id, name, the executable, and
#: whether Kriko itself can download a model through it.
_RUNTIMES = (
    ("ollama", "Ollama", "ollama", True),
    ("lmstudio", "LM Studio", "lms", False),
    ("llamacpp", "llama.cpp", "llama-server", False),
)


def _extra_homes(runtime_id: str) -> list[Path]:
    """Where an installer leaves the program without touching PATH."""
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA")
    if runtime_id == "ollama" and local:
        return [Path(local) / "Programs" / "Ollama" / "ollama.exe"]
    if runtime_id == "lmstudio":
        return [home / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms")]
    return []


def runtimes() -> list[dict]:
    out = []
    for runtime_id, name, executable, can_pull in _RUNTIMES:
        found = shutil.which(executable)
        if not found:
            found = next((str(p) for p in _extra_homes(runtime_id) if p.is_file()), None)
        out.append({
            "id": runtime_id, "name": name, "installed": bool(found),
            "path": found, "can_pull": can_pull,
        })
    return out


def inspect() -> dict:
    gpu = _smi()
    return {
        "gpu": {key: gpu[key] for key in ("name", "vram_total_mb", "vram_used_mb")},
        "gpu_count": gpu["count"],
        "ram_total_mb": _ram_total_mb(),
        "cpu": {"name": _cpu_name(), "cores": os.cpu_count()},
        "os": platform.system() or None,
        "runtimes": runtimes(),
    }


def read(*, fresh: bool = False, now=time.monotonic) -> dict:
    """The machine, from the cache when it is under a minute old."""
    global _cached
    with _lock:
        stamp = now()
        if not fresh and _cached is not None and stamp - _cached[0] < CACHE_SECONDS:
            return _cached[1]
        answer = inspect()
        _cached = (stamp, answer)
        return answer


def forget() -> None:
    global _cached
    with _lock:
        _cached = None
