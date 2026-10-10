"""Run the shared background code in Firefox with an isolated profile/engine.

Requires Mozilla's web-ext CLI in PATH. The fixture changes only the default
loopback port, so an installed Kriko can remain running on 8787. No browsing
history, user profile, Mozilla account or signing settings are used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from app import extension


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--firefox", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--web-ext", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ | {"KRIKO_STORE": str(work / "knowledge.sqlite"),
        "KRIKO_APP_STATE": str(work / "app.sqlite"), "KRIKO_LOG": str(work / "engine.log"),
        "KRIKO_ANALYSES_LOG": str(work / "analyses.jsonl")}
    env.pop("KRIKO_URL", None)
    engine = subprocess.Popen([str(args.engine.resolve()), "--port", "0", "--extension-port", "0",
        "--exit-with-parent"], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=(work / "engine-stderr.txt").open("w"), text=True)
    browser = None
    try:
        line = engine.stdout.readline().strip()
        assert line.startswith("KRIKO_PORT "), line
        port = int(line.split()[1])
        base = f"http://127.0.0.1:{port}"
        target = work / "addon"
        extension.stage(extension.source_dir(), target, "firefox")
        background = target / "background.js"
        background.write_text(background.read_text(encoding="utf-8").replace(
            'const DEFAULT_API_BASE = "http://127.0.0.1:8787";', f'const DEFAULT_API_BASE = "{base}";'),
            encoding="utf-8")
        # Native Firefox APIs, including private session storage and the
        # extension's actual adapters/site-registration path, run in Firefox.
        log = (work / "web-ext.log").open("w")
        command = [str(args.web_ext.resolve()), "run", "--firefox", str(args.firefox.resolve()),
            "--source-dir", str(target), "--firefox-profile", str(work / "profile"),
            "--profile-create-if-missing", "--keep-profile-changes", "--no-reload", "--no-input",
            "--no-config-discovery", "--start-url", "about:blank", "--args=-headless"]
        if os.name == "nt":
            command = ["cmd.exe", "/d", "/c", *command]
        browser = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            if browser.poll() is not None:
                raise RuntimeError((work / "web-ext.log").read_text())
            with urllib.request.urlopen(base + "/api/extension", timeout=5) as response:
                status = json.load(response)
            seen = [row for row in status["sightings"] if row["origin"].startswith("moz-extension://")]
            if seen:
                print(f"Firefox runtime check-in: {seen[0]['origin']}; version {seen[0].get('version')}")
                print(f"Requests observed: {sum(row['hits'] for row in seen)}; isolated loopback port {port}")
                (work / "status.json").write_text(json.dumps(status, indent=2))
                return 0
            time.sleep(0.5)
        raise RuntimeError("Firefox did not reach the isolated Kriko engine within 60 seconds.")
    finally:
        if browser and browser.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(browser.pid)], capture_output=True)
        engine.stdin.close()
        try:
            engine.wait(timeout=20)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(engine.pid)], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
