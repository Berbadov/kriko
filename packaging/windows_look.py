"""Install the MSI, look at every screen of the installed app, uninstall.

    python packaging/windows_look.py kriko-gpui/builds/kriko-<v>-x86_64.msi windows-look

`smoke_app.py` asks whether the freshly built binary stays up. This asks what
a reader on Windows actually gets: the MSI installs per user without a prompt,
the *installed* `kriko.exe` opens each screen (drawn by real DirectX, starting
its own engine), and the MSI removes it again. A screenshot of every screen,
at the default size and at the 940x640 minimum, lands in the output folder
for a person or an agent to look at; the run is the observation the Linux
gate cannot make.

The 1280x860 capture can be clipped on a smaller physical display; the
940x640 minimum capture is always included.

Asserted: the install and uninstall succeed, the installed files appear and
go, and no launch panics or exits on its own. Not asserted: what a screenshot
shows. Pixels are for looking at, and a check on them would fail for reasons
unrelated to the build (see smoke_app.py on why that matters).

The screens are read off the app's own `Tab::key`, so a new screen is looked
at without an edit here.
"""

from __future__ import annotations

import os
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from smoke_app import PANIC, end_tree

ROOT = Path(__file__).resolve().parents[1]

#: The default window and the minimum the app allows.
SIZES = ("1280x860", "940x640")

#: Long enough for a cold engine on the first launch and a screen's first
#: answers after that.
FIRST_HOLD = 30
HOLD = 14


def screens() -> list[str]:
    """Every screen key, from `Tab::key` in the app's source."""
    source = (ROOT / "kriko-gpui" / "src" / "app.rs").read_text(encoding="utf-8")
    body = source[source.index("pub fn key(self)"):]
    body = body[: body.index("\n    }\n")]
    keys = re.findall(r'Tab::\w+ => "([a-z_]+)"', body)
    if not keys:
        raise SystemExit("no screens found in Tab::key")
    return keys


def installed_dir() -> Path:
    """Where the per-user MSI puts the app (`kriko-gpui/wix/main.wxs`)."""
    return Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Kriko"


def screenshot(path: Path) -> None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
        "$g=[System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); "
        f"$bmp.Save('{path}')"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=60)


def msiexec(*args: str, log: Path) -> int:
    return subprocess.run(["msiexec", *args, "/qn", "/l*v", str(log)], timeout=600).returncode


def fixture_data(url: str) -> None:
    """Confirm the isolated service exposes the synthetic history and drafts."""
    def get(path: str) -> dict:
        with urllib.request.urlopen(url + path, timeout=5) as response:
            return json.load(response)

    if not get("/api/health").get("ok"):
        raise RuntimeError("fixture health did not report ok")
    recent = get("/api/history?limit=200").get("items", [])
    drafts = get("/api/compare-drafts").get("items", [])
    if len(recent) < 2 or len(drafts) < 2:
        raise RuntimeError(f"fixture data missing: {len(recent)} recent checks, {len(drafts)} drafts")


def look(exe: Path, out: Path) -> list[str]:
    """Open every screen at every size; return what went wrong."""
    failures: list[str] = []
    scratch = tempfile.TemporaryDirectory(prefix="kriko-look-", ignore_cleanup_errors=True)
    base = os.environ | {
        "KRIKO_STORE": str(Path(scratch.name) / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(Path(scratch.name) / "app.sqlite"),
        "KRIKO_ANALYSES_LOG": str(Path(scratch.name) / "analyses.jsonl"),
        "KRIKO_LOG": str(Path(scratch.name) / "engine.log"),
        "RUST_BACKTRACE": "1",
    }
    base.pop("KRIKO_URL", None)
    first = True
    fixture: subprocess.Popen | None = None
    fixture_log = None
    try:
        for size in SIZES:
            for key in [*screens(), "tutorial"]:
                env = base | {"KRIKO_VERIFY": key, "KRIKO_WINDOW_SIZE": size}
                process = subprocess.Popen(
                    [str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, env=env,
                )
                time.sleep(FIRST_HOLD if first else HOLD)
                first = False
                alive = process.poll() is None
                if alive:
                    screenshot(out / f"{key}-{size}.png")
                    end_tree(process)
                try:
                    said = process.communicate(timeout=20)[0] or ""
                except subprocess.TimeoutExpired:
                    process.kill()
                    said = process.communicate()[0] or ""
                if not alive:
                    failures.append(f"{key} at {size}: exited on its own ({process.returncode})\n{said}")
                elif PANIC in said:
                    failures.append(f"{key} at {size}: panicked\n{said}")
                print(f"{key} at {size}: {'ok' if alive and PANIC not in said else 'FAILED'}")

        ready = Path(scratch.name) / "ready.json"
        fixture_log = (out / "buyer-fixture.log").open("w", encoding="utf-8")
        fixture_env = base | {
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
            "KRIKO_LOG": str(Path(scratch.name) / "fixture-engine.log"),
        }
        fixture = subprocess.Popen(
            [sys.executable, str(ROOT / "packaging" / "buyer_fixture.py"), scratch.name],
            stdout=fixture_log, stderr=subprocess.STDOUT, text=True, env=fixture_env,
        )
        deadline = time.monotonic() + 60
        while not ready.exists() and fixture.poll() is None and time.monotonic() < deadline:
            time.sleep(0.25)
        if not ready.exists():
            failures.append(f"buyer fixture did not become ready; see {out / 'buyer-fixture.log'}")
        else:
            url = json.loads(ready.read_text(encoding="utf-8"))["url"]
            try:
                while True:
                    try:
                        fixture_data(url)
                        break
                    except (OSError, ValueError, RuntimeError):
                        if time.monotonic() >= deadline or fixture.poll() is not None:
                            raise
                        time.sleep(0.25)
            except (OSError, ValueError, RuntimeError) as error:
                failures.append(f"buyer fixture HTTP checks failed: {error}; see {out / 'buyer-fixture.log'}")
            else:
                for key in ("home", "run", "about", "compare", "chat"):
                    env = base | {
                        "KRIKO_URL": url,
                        "KRIKO_VERIFY": key,
                        "KRIKO_WINDOW_SIZE": "940x640",
                    }
                    process = subprocess.Popen(
                        [str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, env=env,
                    )
                    time.sleep(HOLD)
                    alive = process.poll() is None
                    if alive:
                        screenshot(out / f"populated-{key}-940x640.png")
                        end_tree(process)
                    try:
                        said = process.communicate(timeout=20)[0] or ""
                    except subprocess.TimeoutExpired:
                        process.kill()
                        said = process.communicate()[0] or ""
                    if not alive:
                        failures.append(f"populated {key}: exited on its own ({process.returncode})\n{said}")
                    elif PANIC in said:
                        failures.append(f"populated {key}: panicked\n{said}")
                    print(f"populated {key} at 940x640: {'ok' if alive and PANIC not in said else 'FAILED'}")
    finally:
        if fixture is not None and fixture.poll() is None:
            end_tree(fixture)
        if fixture_log is not None:
            fixture_log.close()
        scratch.cleanup()
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    if sys.platform != "win32":
        print("windows_look.py installs an MSI; it runs on Windows only")
        return 2
    msi = Path(argv[1]).resolve()
    out = Path(argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    exe = installed_dir() / "kriko.exe"

    if msiexec("/i", str(msi), log=out / "install.log") != 0:
        print(f"the MSI did not install; see {out / 'install.log'}")
        return 1
    missing = [n for n in ("kriko.exe", "kriko-sidecar.exe") if not (installed_dir() / n).exists()]
    if missing:
        print(f"installed, but {', '.join(missing)} is not in {installed_dir()}")
        return 1
    print(f"installed to {installed_dir()}")

    failures = look(exe, out)

    if msiexec("/x", str(msi), log=out / "uninstall.log") != 0:
        failures.append(f"the MSI did not uninstall; see {out / 'uninstall.log'}")
    elif exe.exists():
        failures.append(f"uninstalled, but {exe} is still there")
    else:
        print("uninstalled; the app's files are gone")

    for failure in failures:
        print(failure)
    print(f"screenshots in {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
