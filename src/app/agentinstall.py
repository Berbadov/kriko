"""Install an agent for the reader, the way its vendor says to, and say if it worked.

A reader who has no coding agent should not have to find a terminal. Each CLI
in `harness.KNOWN` carries `install_command`, the vendor's own Windows
instructions as a PowerShell script; this runs it with the output going to the
job log, then looks again for the CLI the same way the Agents tab does (the
login `PATH`, not this process's stale one), so "installed" means Kriko can now
start it.

The local agent is the same promise for a reader with no account at all: one
click installs Ollama (winget) when it is missing and downloads a small model,
so a plug-and-play machine ends with something that answers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from app import modelpull
from app.loginpath import child_env
from app.providers import harness
from app.winprocess import hidden_startup

LOCAL = "local"

#: The model the one-click local setup downloads: small enough for any laptop
#: (about 1 GB) and the one Kriko is checked against. A reader who wants a
#: bigger one picks it in Local LLM afterwards.
STARTER_MODEL = "qwen3.5:0.8b"

#: Where a freshly installed Ollama listens until the reader says otherwise.
OLLAMA_URL = "http://127.0.0.1:11434"

_OLLAMA = (
    "winget install --id Ollama.Ollama -e --silent "
    "--accept-package-agreements --accept-source-agreements"
)


def command_for(agent_id: str) -> str:
    """The PowerShell script that installs this agent, or "" where there is none."""
    if agent_id == LOCAL:
        return _OLLAMA
    for one in harness.KNOWN:
        if one.id == agent_id:
            return one.install_command
    return ""


def can_install(agent_id: str) -> bool:
    return os.name == "nt" and bool(command_for(agent_id))


def _run(script: str, progress) -> None:
    process = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=child_env(),
        startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tail: list[str] = []
    assert process.stdout is not None
    try:
        for line in process.stdout:
            line = line.strip()
            if line:
                tail = (tail + [line])[-8:]
                progress.log(line[:300])
            progress.check()
    except BaseException:
        process.kill()
        raise
    code = process.wait()
    if code:
        raise RuntimeError(" ".join(tail[-3:]) or f"the installer exited with code {code}")


def _answers(base: str) -> bool:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/api/version", timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _wait_for_ollama(base: str, progress, seconds: int = 90) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _answers(base):
            return True
        progress.check()
        time.sleep(2)
    return False


def _ollama_exe() -> str:
    """Where Ollama is installed on this machine, or "" when it is not."""
    registered = _registered_ollama_exe()
    if registered:
        return registered
    found = shutil.which("ollama", path=child_env()["PATH"])
    if found:
        return found
    own = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    return own if os.path.isfile(own) else ""


def _registered_ollama_exe() -> str:
    """Prefer the vendor's current installation over an obsolete PATH entry."""
    if os.name != "nt":
        return ""
    import winreg

    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, uninstall) as parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    try:
                        with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as entry:
                            name = winreg.QueryValueEx(entry, "DisplayName")[0]
                            if not isinstance(name, str) or not name.startswith("Ollama"):
                                continue
                            location = winreg.QueryValueEx(entry, "InstallLocation")[0]
                            if not isinstance(location, str):
                                continue
                            exe = os.path.join(location, "ollama.exe")
                            if os.path.isfile(exe):
                                return exe
                    except OSError:
                        continue
        except OSError:
            continue
    return ""


def _start_ollama() -> None:
    """Installed is not running: its installer starts it, but a reader who closed it needs it again."""
    exe = _ollama_exe()
    if exe:
        subprocess.Popen(
            [exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _set_up_local(settings, progress) -> dict:
    # "" means nothing answers yet, which is the case this exists for
    base = modelpull.ollama_base(getattr(settings, "app_state_path", None)) or OLLAMA_URL
    if _answers(base):
        progress.log("Ollama is already running.")
    else:
        if _ollama_exe():
            progress.log("Ollama is installed but not running; starting it.")
        else:
            progress.set(0.05, "installing Ollama")
            if not shutil.which("winget", path=child_env()["PATH"]):
                raise RuntimeError("Windows App Installer is missing. Use Download Ollama in Local LLM, run its installer, then press Set up again.")
            if shutil.disk_usage(Path.home()).free < 6 * 1024**3:
                raise RuntimeError("Ollama and the starter model need about 6 GB of free space. Free space or use the manual installer to choose another drive, then retry.")
            _run(_OLLAMA, progress)
        progress.set(0.35, "starting Ollama")
        if not _wait_for_ollama(base, progress, 20):
            _start_ollama()
        if not _wait_for_ollama(base, progress):
            raise RuntimeError("Ollama did not start. Open it from the Start menu once, then press Set up again.")
    if STARTER_MODEL not in [row.get("name") for row in modelpull.installed(base)]:
        progress.set(0.4, f"downloading {STARTER_MODEL}")
        modelpull.pull(base, STARTER_MODEL, progress)
    progress.set(0.95, "Checking that the downloaded model can answer")
    _verify_local(base, STARTER_MODEL, progress)
    progress.set(1.0, f"{STARTER_MODEL} is ready")
    return {"id": LOCAL, "installed": True, "model": STARTER_MODEL}


def _verify_local(base: str, model: str, progress) -> None:
    """A tags/version response does not prove the model runner can start."""
    progress.check()
    request = urllib.request.Request(base.rstrip("/") + "/api/generate", method="POST",
        headers={"Content-Type": "application/json"}, data=json.dumps({
            "model": model, "prompt": "Reply OK.", "stream": False, "think": False,
            "options": {"num_predict": 1, "num_ctx": 2048},
        }).encode("utf-8"))
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
        if (not isinstance(result, dict) or result.get("error") or not result.get("done")
                or not isinstance(result.get("eval_count"), int) or result["eval_count"] < 1):
            raise ValueError("The model did not generate a token")
    except (urllib.error.URLError, OSError, ValueError) as cause:
        raise RuntimeError(
            "Ollama is running, but the model could not answer. Restart Ollama and retry. "
            "If it still fails, use Download Ollama to update or repair its installation, "
            "then press Set up again. You do not need to delete your downloaded models."
        ) from cause
    progress.check()


def install(settings, params: dict, progress) -> dict:
    agent_id = str(params.get("agent_id") or "")
    if os.name != "nt":
        raise RuntimeError("One-click install is for Windows. Use the install line on the card.")
    if not command_for(agent_id):
        raise ValueError(f"there is no one-click install for {agent_id!r}")
    if agent_id == LOCAL:
        result = _set_up_local(settings, progress)
        path = getattr(settings, "app_state_path", None)
        if path is not None:
            from app import prefs
            from app.web import state
            conn = state.connect(path)
            try:
                prefs.write(conn, {prefs.LOCAL_URL: modelpull.ollama_base(path) or OLLAMA_URL,
                                   prefs.LOCAL_MODEL: result["model"]})
            finally:
                conn.close()
        return result
    progress.set(0.1, "installing")
    _run(command_for(agent_id), progress)
    harness.forget_located()
    one = next(h for h in harness.KNOWN if h.id == agent_id)
    path = harness.locate(one)
    if not path:
        raise RuntimeError(
            f"{one.label} installed, but Kriko cannot find it yet. Close and reopen Kriko, then check again.")
    progress.set(1.0, f"{one.label} is ready")
    return {"id": agent_id, "installed": True, "path": path}


def start_local(progress) -> dict:
    """Start an existing Ollama without installing or downloading anything."""
    if _answers(OLLAMA_URL):
        return {"url": OLLAMA_URL, "ready": True}
    if not _ollama_exe():
        raise RuntimeError("Ollama is not installed. Use Set up Ollama or Download Ollama in Local LLM first.")
    progress.set(0.1, "Starting Ollama")
    _start_ollama()
    if not _wait_for_ollama(OLLAMA_URL, progress, 30):
        raise RuntimeError("Ollama did not answer. Open Ollama from the Start menu, then press Check again.")
    progress.set(1.0, "Ollama is running")
    return {"url": OLLAMA_URL, "ready": True}
