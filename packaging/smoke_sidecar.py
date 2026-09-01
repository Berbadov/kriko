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
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PORT_LINE = "KRIKO_PORT"
TIMEOUT = 60


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    binary = Path(argv[1]).resolve()
    if not binary.exists():
        print(f"no such binary: {binary}")
        return 1

    process = subprocess.Popen(
        [str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
            print("the sidecar announced a port it never served")
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
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
