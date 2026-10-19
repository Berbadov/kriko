"""Install an agent for the reader, the way its vendor says to, and say if it worked.

A reader who has no coding agent should not have to find a terminal. Each CLI
in `harness.KNOWN` carries `install_command`, the vendor's own Windows
instructions as a PowerShell script; this runs it with the output going to the
job log, then looks again for the CLI the same way the Agents tab does (the
login `PATH`, not this process's stale one), so "installed" means Kriko can now
start it.

The local agent is the same promise for a reader with no account at all: one
click installs Ollama when it is missing and downloads a model, so a
plug-and-play machine ends with something that answers.

Ollama is fetched from its own site and run by its own installer, and the job
never waits on a pipe: see `_stream` for why that matters.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from app import modelpull
from app.localplane import RECOMMENDED_MODEL
from app.loginpath import child_env
from app.providers import harness
from app.providers.local_discovery import forget_discovery
from app.providers.local_inference import forget_incomplete
from app.winprocess import hidden_startup

LOCAL = "local"

#: What the one-click setup downloads: the model Kriko recommends everywhere
#: else (`localplane.RECOMMENDED_MODEL`), whatever the machine. It is chosen by
#: how it performs on the Quick Look pipeline, not by how much memory is free.
STARTER_MODEL = RECOMMENDED_MODEL

#: Where a freshly installed Ollama listens until the reader says otherwise.
OLLAMA_URL = "http://127.0.0.1:11434"
#: The port `OLLAMA_URL` names, as a number: `_stop_ollama` asks the kernel who
#: is listening on it rather than killing every process called `ollama.exe`.
OLLAMA_PORT = 11434

#: Ollama's own installer, from its own site. Not winget: that waits on the
#: Store sources, asks questions a hidden window cannot answer, and was the
#: install that stalled. This is one HTTPS download with a byte count, then a
#: per-user installer that needs no administrator.
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"

#: The installer is signed; the signer must say Ollama before it is run.
OLLAMA_SIGNER = "Ollama"

#: How long the silent installer may take before the job gives up on it.
INSTALL_SECONDS = 900


def command_for(agent_id: str) -> str:
    """What installs this agent: a PowerShell script, or for `local` the
    address of Ollama's installer. "" where there is none."""
    if agent_id == LOCAL:
        return OLLAMA_SETUP_URL
    for one in harness.KNOWN:
        if one.id == agent_id:
            return one.install_command
    return ""


def can_install(agent_id: str) -> bool:
    return os.name == "nt" and bool(command_for(agent_id))


def _run(script: str, progress) -> None:
    _stream(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script], progress)


def _kill_tree(process: subprocess.Popen) -> None:
    """End the process and what it started: killing only the shell leaves the installer."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                           timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    process.kill()


#: What a console spinner prints between real lines.
_SPINNER = set("-\\|/ ")


def _stream(argv: list[str], progress, *, grace: float = 2.0) -> None:
    """Run `argv`, relay its output to the job log, and return when *it* exits.

    Two things the plain `for line in process.stdout` got wrong, and both were
    the reader's "install does nothing and stalls with some loading logs":

    * An installer that starts the program it installed leaves that program
      holding the output pipe, so reading to end-of-file waits for it to quit,
      which it never does. The process's own exit is the end, and the output
      gets `grace` seconds more to drain.
    * A quiet installer prints nothing, so Cancel, checked once per line, was
      never seen. The wait polls instead.
    """
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", env=child_env(),
        startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: queue.Queue = queue.Queue()
    assert process.stdout is not None

    def pump() -> None:
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                lines.put(line)
        except (OSError, ValueError):
            pass
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    tail: list[str] = []
    ended = False

    def take(wait: float) -> None:
        nonlocal ended
        try:
            line = lines.get(timeout=wait)
        except queue.Empty:
            return
        if line is None:
            ended = True
            return
        line = line.strip()
        if line and not set(line) <= _SPINNER:
            tail.append(line)
            del tail[:-8]
            progress.log(line[:300])

    try:
        while process.poll() is None:
            take(0.25)
            progress.check()
        deadline = time.monotonic() + grace
        while not ended and time.monotonic() < deadline:
            take(0.1)
    except BaseException:
        _kill_tree(process)
        raise
    code = process.wait()
    if code:
        raise RuntimeError(" ".join(tail[-3:]) or f"the installer exited with code {code}")


def _download_ollama(dest: str, progress) -> None:
    """Ollama's installer, to `dest`, with the byte count in the job's bar."""
    request = urllib.request.Request(OLLAMA_SETUP_URL, headers={"User-Agent": "Kriko"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            got, last = 0, 0.0
            while True:
                progress.check()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                now = time.monotonic()
                if now - last >= 0.4:
                    last = now
                    say = (f"downloading Ollama, {got / 1e6:.0f} of {total / 1e6:.0f} MB" if total
                           else f"downloading Ollama, {got / 1e6:.0f} MB")
                    progress.set(0.02 + 0.2 * (got / total if total else 0.5), say)
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError(
            f"Could not download Ollama ({error}). Check the internet connection, or use "
            "Download Ollama manually in Local LLM.") from error
    if not os.path.getsize(dest):
        raise RuntimeError("Ollama's download came back empty. Retry, or use Download Ollama manually.")


def _signer_of(path: str) -> tuple[str, str]:
    """`(status, subject)` of a file's Authenticode signature, as Windows reports it."""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:KRIKO_FILE; "
              '"$($s.Status)|$($s.SignerCertificate.Subject)"')
    # Windows PowerShell must pick its own module path. One inherited from
    # PowerShell 7 (set wherever 7 is installed and launched us) lists modules
    # 5.1 cannot load, and the signature cmdlet then fails with no output.
    env = {key: value for key, value in child_env().items() if key.casefold() != "psmodulepath"}
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=90, env={**env, "KRIKO_FILE": path},
        startupinfo=hidden_startup(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    status, _, subject = (done.stdout or "").strip().partition("|")
    return status, subject


def _install_ollama(progress) -> None:
    """Download, check the signature, and run Ollama's own installer silently."""
    folder = tempfile.mkdtemp(prefix="kriko-ollama-")
    setup = os.path.join(folder, "OllamaSetup.exe")
    try:
        progress.set(0.02, "downloading Ollama")
        _download_ollama(setup, progress)
        progress.set(0.22, "checking the installer's signature")
        try:
            status, subject = _signer_of(setup)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"Could not check the installer's signature ({error}); it was not run.") from error
        if status != "Valid" or OLLAMA_SIGNER.casefold() not in subject.casefold():
            raise RuntimeError(
                f"The downloaded installer is not signed by Ollama (signature {status or 'unreadable'}); "
                "it was not run. Use Download Ollama manually in Local LLM.")
        progress.set(0.25, "installing Ollama")
        process = subprocess.Popen(
            [setup, "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=hidden_startup(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + INSTALL_SECONDS
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise RuntimeError("Ollama's installer did not finish in 15 minutes. Close it and retry.")
                progress.check()
                time.sleep(0.5)
        except BaseException:
            _kill_tree(process)
            raise
        if process.returncode:
            raise RuntimeError(f"Ollama's installer exited with code {process.returncode}.")
        progress.log("Ollama installed.")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


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
    # `sys.platform`, not `os.name`: mypy understands only the former, and it
    # is what keeps the winreg attributes out of a Linux type check.
    if sys.platform != "win32":
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


def _starter(progress) -> str:
    """The model to download, and a log line that says why."""
    progress.log(f"Choosing {STARTER_MODEL}, the recommended model.")
    return STARTER_MODEL


class _BrokenRuntime(RuntimeError):
    """Ollama answers, but cannot start a model: an install that is not whole."""


def _stop_ollama() -> None:
    """End the Ollama this app installed, so its files can be replaced.

    This used to be `taskkill /F /IM "ollama app.exe"` and the same for
    `ollama.exe`: that kills **every** Ollama on the machine by image name —
    another user's, another app's, one the reader started deliberately for
    something else. What this needs is the process holding the port Kriko is
    about to replace the files behind, so it asks for that one and kills its
    tree (`processcontrol`, the same way every other spawn in this tree is
    ended). If nothing is listening, there is nothing to stop.
    """
    if os.name != "nt":
        return
    from app import processcontrol

    pid = processcontrol.listener_pid(OLLAMA_PORT)
    if not pid:
        return
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass
    # Wait for the port to actually go, rather than assuming a fixed sleep did
    # it: the file replacement this precedes fails if the handle is still open.
    for _ in range(60):
        if not processcontrol.listener_pid(OLLAMA_PORT):
            return
        time.sleep(0.25)


def _start_and_wait(base: str, progress) -> None:
    progress.set(0.35, "starting Ollama")
    if not _wait_for_ollama(base, progress, 20):
        _start_ollama()
    if not _wait_for_ollama(base, progress):
        raise RuntimeError("Ollama installed but did not start. Open it from the Start menu once, then press Set up again.")


def _set_up_local(settings, progress) -> dict:
    # "" means nothing answers yet, which is the case this exists for
    base = modelpull.ollama_base(getattr(settings, "app_state_path", None)) or OLLAMA_URL
    model = _starter(progress)
    if _answers(base):
        progress.log("Ollama is already running.")
    else:
        if _ollama_exe():
            progress.log("Ollama is installed but not running; starting it.")
        else:
            if shutil.disk_usage(Path.home()).free < 8 * 1024**3:
                raise RuntimeError("Ollama and the starter model need about 8 GB of free space. Free space or use the manual installer to choose another drive, then retry.")
            _install_ollama(progress)
        _start_and_wait(base, progress)
    if model not in [row.get("name") for row in modelpull.installed(base)]:
        progress.set(0.4, f"downloading {model}")
        modelpull.pull(base, model, progress)
    progress.set(0.95, "Checking that the downloaded model can answer")
    try:
        _verify_local(base, model, progress)
    except _BrokenRuntime as broken:
        # A stalled or interrupted installer leaves `ollama.exe` with no model
        # runner beside it. It looks installed and answers /api/version, and
        # nothing it holds can ever run, so the only repair is the installer
        # again, over the top; the downloaded models are kept.
        progress.log(f"Ollama is installed but incomplete ({broken}); reinstalling it.")
        _stop_ollama()
        _install_ollama(progress)
        _start_and_wait(base, progress)
        progress.set(0.95, "Checking that the downloaded model can answer")
        _verify_local(base, model, progress)
    # It answered, so a "not ready, incomplete install" noted earlier is stale.
    # And so is anything remembered about what this machine serves: the install
    # that just finished is exactly the event a remembered "nothing answers"
    # would otherwise outlive by `DISCOVERY_TTL_S`.
    forget_incomplete(base)
    forget_discovery()
    progress.set(1.0, f"{model} is ready")
    return {"id": LOCAL, "installed": True, "model": model}


#: What Ollama says when its model runner is missing or will not start; these
#: mean the install is not whole, where "out of memory" means the machine is.
_INCOMPLETE = ("llama-server", "binary not found", "runner")


def _verify_local(base: str, model: str, progress) -> None:
    """A tags/version response does not prove the model runner can start."""
    progress.check()
    request = urllib.request.Request(base.rstrip("/") + "/api/generate", method="POST",
        headers={"Content-Type": "application/json"}, data=json.dumps({
            "model": model, "prompt": "Reply OK.", "stream": False, "think": False,
            "options": {"num_predict": 1, "num_ctx": 2048},
        }).encode("utf-8"))
    said = ""
    try:
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            said = modelpull._error_text(error.read())
            raise
        if isinstance(result, dict) and result.get("error"):
            said = str(result["error"])
        if (not isinstance(result, dict) or result.get("error") or not result.get("done")
                or not isinstance(result.get("eval_count"), int) or result["eval_count"] < 1):
            raise ValueError("The model did not generate a token")
    except (urllib.error.URLError, OSError, ValueError) as cause:
        if any(word in said.casefold() for word in _INCOMPLETE):
            raise _BrokenRuntime(said[:160]) from cause
        raise RuntimeError(
            "Ollama is running, but the model could not answer"
            + (f" ({said[:160]})" if said else "")
            + ". Restart Ollama and retry. "
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


_WAKE_LOCK = threading.Lock()


def wake_local(base: str = OLLAMA_URL, progress=None, seconds: int = 30) -> bool:
    """Start an installed Ollama that nobody is running, and wait until it answers.

    Asking a question of the Local model is the reader saying they want it, so
    a closed Ollama is started for them rather than reported. False means it
    could not be (not installed, or it did not answer in `seconds`); the run
    then fails with its own reason. Runs are concurrent, so one starts it and
    the rest wait on the same answer.
    """
    with _WAKE_LOCK:
        if _answers(base):
            return True
        if not _ollama_exe():
            return False
        if progress is not None:
            progress.log("Ollama is installed but not running; starting it.")
        _start_ollama()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if _answers(base):
                forget_discovery()
                return True
            if progress is not None:
                progress.check()
            time.sleep(0.5)
    return False


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
