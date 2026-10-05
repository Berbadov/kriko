"""Does the desktop app actually start?

    python packaging/smoke_app.py kriko-gpui/target/release/kriko.exe

CI proved the sidecar answers (`smoke_sidecar.py`) and proved the installer
builds. Nothing proved the *app* starts, and v0.2.4 is what that gap looks
like: green builds, published installers, and an app that panicked before it
drew a window, to a stderr no double-click has. So the app is launched here,
held for a few seconds, and asked two questions that need no window server to
answer:

* is it still running?
* did it panic?

Deliberately not "did a window appear": a window on a headless runner is a
different and flakier question than the one that broke, and a check that fails
for reasons unrelated to the build ends up disabled. What the app does with
the engine is *reported* (was `kriko-sidecar` started as its child) and never
asserted; `smoke_sidecar.py` covers the engine itself.

A second Kriko exits at once when one is already open (one Kriko per
machine), which this reports as the failure it would otherwise hide: close the
running one, or it is the running one that was tested.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: Long enough for the window, the tray and the engine start; short enough
#: that a hung runner is not the way this is discovered.
HOLD = 25

#: Rust's panic hook writes this, whatever the message is.
PANIC = "panicked at"


def sidecar_started(parent: int) -> bool:
    """Did the app get far enough to start an engine of its own? Reported, not asserted.

    By parent, not by name: a Kriko the reader has open elsewhere has an
    engine too, and this must be about the one that was just launched.
    """
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={parent}' "
                    "| Where-Object { $_.Name -like 'kriko-sidecar*' } "
                    "| Measure-Object).Count",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
            return out.strip() not in ("", "0")
        out = subprocess.run(
            ["pgrep", "-P", str(parent), "-f", "kriko-sidecar|app.sidecar"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def end_tree(process: subprocess.Popen) -> None:
    """Stop the app and everything it started, and only that.

    On Windows a one-file sidecar re-executes, so its pid is a bootloader and
    the child holds the image mapped; `/T` takes the whole tree. By pid, not
    by image name, so a Kriko the reader has open is left alone.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True
        )
    else:
        process.kill()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    binary = Path(argv[1]).resolve()
    if not binary.exists():
        print(f"no such binary: {binary}")
        return 1

    # Same reason as smoke_sidecar.py: the runner's own ~/.kriko is not this
    # test's to write, and a pass that depends on what is already installed
    # there is not a pass.
    scratch = tempfile.TemporaryDirectory(
        prefix="kriko-app-smoke-", ignore_cleanup_errors=True
    )
    environment = os.environ | {
        "KRIKO_STORE": str(Path(scratch.name) / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(Path(scratch.name) / "app.sqlite"),
        "KRIKO_ANALYSES_LOG": str(Path(scratch.name) / "analyses.jsonl"),
        "RUST_BACKTRACE": "1",
    }
    process = subprocess.Popen(
        [str(binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    try:
        deadline = time.time() + HOLD
        while time.time() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() or "(it wrote nothing)"
                print(f"the app exited on its own with code {process.returncode}")
                print(output)
                return 1
            time.sleep(0.5)

        spawned = sidecar_started(process.pid)
        end_tree(process)
        try:
            output = process.communicate(timeout=20)[0] or ""
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate()[0] or ""

        if PANIC in output:
            print("the app panicked while starting:")
            print(output)
            return 1

        print(f"the app stayed up for {HOLD}s and did not panic")
        print(
            "engine spawned: yes"
            if spawned
            else "engine spawned: not seen (no kriko-sidecar beside the app, or it "
            "attached to a running engine; not a failure here, smoke_sidecar.py "
            "covers the engine)"
        )
        if output.strip():
            print(f"--- what it said ---\n{output.strip()}")
        return 0
    finally:
        if process.poll() is None:
            end_tree(process)
        scratch.cleanup()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
