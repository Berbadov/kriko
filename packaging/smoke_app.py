"""Does the bundled shell actually open?

    python packaging/smoke_app.py tauri/src-tauri/target/release/kriko

CI proved the sidecar answers (`smoke_sidecar.py`) and proved the installers
build. Nothing proved the *shell* starts, and v0.2.4 is what that gap looks
like: three green runners, four published installers, and an app that panicked
in `build().expect(..)` before it drew a window, because a plugin's config is
written at package time and the plugin was registered unconditionally.

    PluginInitialization("updater", "invalid type: null, expected struct Config")

That failure is invisible by construction — a GUI build writes its panic to a
stderr no double-click has. So the shell is launched here, held for a few
seconds, and asked two questions that need no window server to answer:

* is it still running?
* did it panic?

Deliberately not "did a window appear". A webview on a headless runner is a
different and flakier question than the one that broke, and a check that fails
for reasons unrelated to the build would end up disabled — so the window is
*reported* (via the sidecar it spawns) and never asserted.
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: Long enough for plugin init, `setup`, and the frontend's `start_engine`;
#: short enough that a hung runner is not the way this is discovered.
HOLD = 25

#: Rust's panic hook writes this, whatever the message is.
PANIC = "panicked at"


def sidecar_running() -> bool:
    """Did the shell get far enough to spawn an engine? Reported, not asserted."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq kriko-sidecar.exe"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
            return "kriko-sidecar" in out
        out = subprocess.run(
            ["pgrep", "-f", "kriko-sidecar"], capture_output=True, text=True, timeout=30
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
                print(f"the shell exited on its own with code {process.returncode}")
                print(output)
                return 1
            time.sleep(0.5)

        process.terminate()
        try:
            output = process.communicate(timeout=20)[0] or ""
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate()[0] or ""

        if PANIC in output:
            print("the shell panicked while starting:")
            print(output)
            return 1

        print(f"the shell stayed up for {HOLD}s and did not panic")
        print(
            "engine spawned: yes"
            if sidecar_running()
            else "engine spawned: not seen — the webview may not have run "
            "(not a failure here; smoke_sidecar.py covers the engine)"
        )
        if output.strip():
            print(f"--- what it said ---\n{output.strip()}")
        return 0
    finally:
        if process.poll() is None:
            process.kill()
        # A shell killed mid-launch can leave the engine it spawned behind, and
        # on Windows that engine holds its own image mapped — the next step in
        # the job would fail to overwrite it.
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", "kriko-sidecar.exe"],
                capture_output=True,
            )
        else:
            subprocess.run(["pkill", "-f", "kriko-sidecar"], capture_output=True)
        scratch.cleanup()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
