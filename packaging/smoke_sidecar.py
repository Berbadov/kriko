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
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            print(process.stderr.read() or "(the sidecar wrote nothing to stderr)")
            return 1

        print(f"health ok: {health}")

        # The frontend is loaded from the filesystem, not imported, so a
        # missing `datas` entry only shows up as a 404 here.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ) as response:
            page = response.read().decode("utf-8", "replace")
        if "<div id=\"app\"" not in page and "<script" not in page:
            print("the sidecar served no frontend — check the spec's datas entry")
            return 1
        print("frontend ok")

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
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        scratch.cleanup()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
