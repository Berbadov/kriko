"""Does the frozen sidecar still do the one thing the shell needs?

Run against a PyInstaller build, not against the source tree:

    python packaging/smoke_sidecar.py dist/kriko-sidecar

Freezing breaks this handshake in ways the pytest suite cannot see — a missing
hidden import, a buffered stdout, a `datas` entry that did not make it — and
each of those looks identical from the outside: a window that never opens. So
the check runs in CI between "freeze" and "bundle", where the failure still has
a name.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT_LINE = "KRIKO_PORT"
TIMEOUT = 60


def end(process: subprocess.Popen, *, timeout: float = 15) -> None:
    """Stop a frozen sidecar, including the child that actually holds the image.

    `process.terminate()` is not enough on Windows, and the reason is
    PyInstaller: a onefile binary unpacks itself and re-execs, so the pid we
    spawned is the bootloader and its *child* is the Python process holding
    `kriko-sidecar.exe` mapped. Kill the parent and the child keeps running --
    an orphan that owns the store's WAL lock and, worse, owns the file the next
    build has to overwrite.

    Not hypothetical. The second local run of `packaging/build_desktop.ps1`
    died at the freeze step with

        PermissionError: [WinError 5] Access is denied: 'dist\\kriko-sidecar.exe'

    because the *previous* run's smoke test had left one behind. `tauri/` has
    tree-killed since v0.2.x for exactly this reason and its README says so;
    these smoke tests did not, and on a CI runner that is deleted afterwards
    nobody ever noticed. The moment the build ran twice on one machine -- which
    is the whole point of `build_desktop.ps1` -- it mattered.

    By pid rather than by image name: `taskkill /IM kriko-sidecar.exe` would
    also kill an installed Kriko the person at the keyboard is using.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()


def fetch(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.load(r)


def post(port: int, path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as error:
        return {"error": error.read().decode("utf-8", "replace"), "status": error.code}


def mcp_speaks(binary: Path, environment: dict) -> bool:
    """Does `--mcp` still complete a real handshake?

    Its own subprocess, because MCP mode owns stdio and the HTTP mode above owns
    a port; nothing is shared but the binary. FastMCP resolves transports and
    validators by string at import time, so this is the check that a frozen
    build did not silently lose the agents' only door into an installed app.
    """
    process = subprocess.Popen(
        [str(binary), "--mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "smoke", "version": "0"},
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        deadline = time.time() + 60
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            try:
                body = json.loads(line)
            except ValueError:
                continue
            if body.get("result", {}).get("serverInfo", {}).get("name") == "kriko":
                print("mcp ok: initialize answered")
                return True
            print(f"the MCP server answered oddly: {body}")
            return False
        print("the MCP server never answered initialize")
        print(process.stderr.read() or "(it wrote nothing to stderr)")
        return False
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        end(process)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    binary = Path(argv[1]).resolve()
    if not binary.exists():
        print(f"no such binary: {binary}")
        return 1

    # A smoke test that writes to ~/.kriko would both pollute the reader's own
    # store and read its data back — a lookup that only passes because the
    # developer happens to have the cars pack installed is not a smoke test.
    # ignore_cleanup_errors: Windows refuses to remove a directory anything
    # still has open, and a process that has just been terminated is not yet a
    # process that has let go of its SQLite files. A leftover temp directory is
    # not a smoke-test failure; every check above it already passed.
    scratch = tempfile.TemporaryDirectory(
        prefix="kriko-smoke-", ignore_cleanup_errors=True
    )
    environment = os.environ | {
        "KRIKO_STORE": str(Path(scratch.name) / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(Path(scratch.name) / "app.sqlite"),
        "KRIKO_ANALYSES_LOG": str(Path(scratch.name) / "analyses.jsonl"),
        # Into scratch so the assertion below is about *this* run and not
        # about a log some earlier run left in the runner's home.
        "KRIKO_LOG": str(Path(scratch.name) / "logs" / "app.log"),
    }
    process = subprocess.Popen(
        [str(binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        line = process.stdout.readline().strip()
        if not line.startswith(PORT_LINE):
            print(f"the sidecar did not announce a port. First line: {line!r}")
            print(process.stderr.read())
            return 1
        port = int(line.split()[1])
        print(f"handshake ok: port {port}")

        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=2
                ) as response:
                    health = json.load(response)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(0.2)
        else:
            # Dump stderr before giving up. This is the failure mode a Windows
            # runner hit — port printed, nothing listening — and "announced a
            # port it never served" with no traceback under it cost a whole
            # CI round-trip to diagnose.
            print("the sidecar announced a port it never served")
            end(process, timeout=10)
            print(process.stderr.read() or "(the sidecar wrote nothing to stderr)")
            return 1

        print(f"health ok: {health}")

        # ── is anything being written down? ───────────────────────────────
        #
        # This is the gate that was missing for two months. The analysis log
        # reported its own failures through `log.warning` into a root logger
        # with no handler, so a `PermissionError` on every single append
        # produced no output anywhere and `analyses.jsonl` stayed empty. Every
        # other gate was green throughout, including this smoke test, because
        # nothing here had ever asked whether the log existed.
        #
        # It is checked in the *frozen binary* rather than only in pytest
        # because that is where the paths differ: `sys._MEIPASS` is a
        # temporary directory that vanishes, an installed app runs from
        # Program Files, and both are exactly the cases a source checkout
        # cannot reproduce.
        log_file = health.get("log_file")
        if not log_file:
            print(
                "the sidecar is writing no log at all: "
                f"{health.get('log_problem') or '(no reason given)'}"
            )
            return 1
        if not Path(log_file).exists():
            print(f"the sidecar named a log at {log_file} and never created it")
            return 1
        if health.get("log_problem"):
            print(f"the log is degraded: {health['log_problem']}")
            return 1
        # The analysis log was pointed at scratch above, so a fallback here
        # means `resolve_writable` refused a path we know is writable.
        if health.get("analysis_log_problem"):
            print(
                "the analysis log fell back even though its path was ours: "
                f"{health['analysis_log_problem']}"
            )
            return 1
        print(f"log ok: {log_file}")

        # Unsupervised on purpose — nothing is reading this process's stdout,
        # and the honest answer is what the extension branches on. A binary
        # that claimed a shell here would send "Open in Kriko" back to doing
        # nothing at all.
        if health.get("shell_attached"):
            print("the sidecar claims a desktop shell nobody attached")
            return 1

        # The frontend is loaded from the filesystem, not imported, so a
        # missing `datas` entry only shows up as a 404 here.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ) as response:
            page = response.read().decode("utf-8", "replace")
        if "<div id=\"app\"" not in page and "<script" not in page:
            print("the sidecar served no frontend -- check the spec's datas entry")
            return 1
        print("frontend ok")

        # The browser extension is data too, and it fails the same way the
        # frontend does: silently, in a shipped installer, on the one page a
        # reader opens *because* they need help. `available: false` here means
        # the spec's `datas` lost it.
        ext = fetch(port, "/api/extension")
        if not ext.get("available"):
            print("the sidecar carries no browser extension -- check the spec's datas")
            return 1
        print(f"extension ok: version {ext.get('version')}")

        # Beyond liveness. Each of these fails *only* when freezing dropped
        # something, and each drops a different module graph:
        #   lookup   -> kriko.lookup + the store
        #   jobs     -> the runner thread and its own sqlite connection
        #   research -> kriko.research, imported by app/web/tasks.py
        # A binary that answers /api/health and nothing else is exactly the
        # bundle we would otherwise ship.
        lookup = post(
            port, "/api/lookup", {"kind": "product", "identity": {}, "context": {}}
        )
        if "claims" not in lookup:
            print(f"the engine could not answer a lookup: {lookup}")
            return 1
        print(f"lookup ok: coverage {lookup.get('coverage')}")

        job = post(port, "/api/research", {"subject_id": "smoke-test-no-such-subject"})
        if "job_id" not in job:
            print(f"the job runner did not accept work: {job}")
            return 1
        deadline = time.time() + 30
        row = {}
        while time.time() < deadline:
            row = fetch(port, f"/api/jobs/{job['job_id']}")
            if row.get("done"):
                break
            time.sleep(0.2)
        else:
            print("a job was accepted and then never finished")
            return 1
        # It *should* fail — there is no such subject. What matters is that it
        # failed with an explanation rather than an ImportError, which is what
        # a missing hidden import looks like from here.
        if row.get("state") != "failed":
            print(f"expected the job to fail cleanly, got {row}")
            return 1
        if "ModuleNotFoundError" in row.get("log", ""):
            print(f"the frozen binary is missing a module:\n{row['log']}")
            return 1
        print(f"job ok: failed cleanly with {row['message']!r}")

        if not mcp_speaks(binary, environment):
            return 1
        return 0
    finally:
        end(process)
        scratch.cleanup()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
