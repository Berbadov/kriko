"""How long the sidecar takes from launch to its first healthy answer.

The desktop shell starts `app.sidecar`, blocks on the `KRIKO_PORT <n>` line,
then polls `/api/health` until it gets a 200. This measures that same path,
in a child process whose HOME is a throwaway directory, so the reader's
`~/.kriko` is never read or written:

    python tools/bench_startup.py --runs 3
    python tools/bench_startup.py --runs 3 --store path/to/knowledge.sqlite
    python tools/bench_startup.py --runs 3 --store path/to/knowledge.sqlite --reuse-home

`--store` copies an existing store into the throwaway home first, so the
health answer is measured against real packs; without it the store is absent
(a first run). The copy is what the sidecar writes to, never the original.

By default every run gets a fresh home (a first start on a new machine).
`--reuse-home` keeps one home across runs after a discarded warm-up, which is
what a reader's later starts look like: the app-state file, the staged
extension and the agent-skill state already exist.

Output is one line per run and a median. `port_ms` is launch to the handshake
line; `health_ms` is launch to the first 200 from `/api/health`.
"""

import argparse
import http.client
import json
import os
import queue
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORT_LINE = "KRIKO_PORT"


def child_env(home: Path, repo: Path = REPO) -> dict:
    """The sidecar's environment: its own HOME, the given checkout's sources.

    `KRIKO_NO_PACK_AUTOUPDATE` keeps the weekly pack check off the network,
    which would otherwise make the timing depend on the reader's connection.
    """
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PYTHONPATH"] = f"{repo / 'src'}{os.pathsep}{repo}"
    env["KRIKO_NO_PACK_AUTOUPDATE"] = "1"
    return env


def launch(python: str, home: Path, store: Path, repo: Path = REPO) -> subprocess.Popen:
    argv = [python, "-m", "app.sidecar", "--port", "0", "--extension-port", "0",
            "--exit-with-parent", "--store", str(store)]
    return subprocess.Popen(
        argv, cwd=str(repo), env=child_env(home, repo),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )


def read_port(proc: subprocess.Popen, timeout: float) -> int:
    """The first stdout line that starts with KRIKO_PORT, with a deadline."""
    lines: queue.Queue = queue.Queue()

    def pump() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.perf_counter() + timeout
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError("no KRIKO_PORT line")
        line = lines.get(timeout=remaining)
        if line is None:
            raise RuntimeError("sidecar exited before announcing a port")
        if line.startswith(PORT_LINE):
            return int(line.split()[1])


def seed(home: Path, store: Path | None) -> Path:
    """Copy the store into the home, and return the path the sidecar will use."""
    target = home / ".kriko" / "knowledge.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    if store is not None:
        shutil.copy(store, target)
    return target


def one_run(python: str, home: Path, store: Path, timeout: float, repo: Path = REPO) -> dict:
    started = time.perf_counter()
    proc = launch(python, home, store, repo)
    try:
        port = read_port(proc, timeout)
        port_ms = (time.perf_counter() - started) * 1000
        health_ms = None
        while time.perf_counter() - started < timeout:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                response.read()
                conn.close()
                if response.status == 200:
                    health_ms = (time.perf_counter() - started) * 1000
                    break
            except OSError:
                pass
            time.sleep(0.002)
        if health_ms is None:
            raise TimeoutError("/api/health never answered 200")
        return {"port_ms": round(port_ms, 1), "health_ms": round(health_ms, 1)}
    finally:
        if proc.stdin:
            proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--store", type=Path, default=None,
                        help="copy this store into the throwaway home first")
    parser.add_argument("--reuse-home", action="store_true",
                        help="one home for all runs, after a discarded warm-up")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--repo", type=Path, default=REPO,
                        help="checkout whose src/ runs (default: this one)")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)

    results = []
    with tempfile.TemporaryDirectory(prefix="kriko-bench-") as tmp:
        if args.reuse_home:
            home = Path(tmp)
            store = seed(home, args.store)
            one_run(args.python, home, store, args.timeout, args.repo)  # warm-up, not reported
        for index in range(args.runs):
            if not args.reuse_home:
                home = Path(tmp) / f"run-{index}"
                store = seed(home, args.store)
            result = one_run(args.python, home, store, args.timeout, args.repo)
            results.append(result)
            if not args.json:
                print(f"run {index + 1}: port {result['port_ms']} ms, "
                      f"health 200 at {result['health_ms']} ms", flush=True)
    summary = {
        "reuse_home": args.reuse_home,
        "runs": results,
        "median_port_ms": round(statistics.median(r["port_ms"] for r in results), 1),
        "median_health_ms": round(statistics.median(r["health_ms"] for r in results), 1),
    }
    if args.json:
        print(json.dumps(summary))
    else:
        print(f"median: port {summary['median_port_ms']} ms, "
              f"health 200 at {summary['median_health_ms']} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
