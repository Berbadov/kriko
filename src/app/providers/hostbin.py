"""The Rust helper that finds CLIs and asks them short questions.

`kriko-harness` sits beside the sidecar in an install and under
`kriko-harness/target/` in a checkout. Without it every call here returns
`None` and the caller does the work in Python, so a missing binary slows the
app and never breaks it.
"""

import functools
import json
import os
import subprocess
import sys
from pathlib import Path

from app.winprocess import hidden_startup

ENV = "KRIKO_HARNESS_BIN"
_NAME = "kriko-harness.exe" if os.name == "nt" else "kriko-harness"


@functools.cache
def binary() -> str:
    beside = Path(sys.executable).with_name(_NAME)
    checkout = Path(__file__).resolve().parents[3] / "kriko-harness" / "target"
    candidates = [Path(os.environ[ENV])] if os.environ.get(ENV) else []
    candidates += [beside, *(checkout / kind / _NAME for kind in ("release", "debug"))]
    return next((str(c) for c in candidates if c.is_file()), "")


def _call(request: dict, wait: float) -> dict | None:
    exe = binary()
    if not exe:
        return None
    try:
        done = subprocess.run(
            [exe], input=json.dumps(request), capture_output=True, text=True, encoding="utf-8",
            timeout=wait, startupinfo=hidden_startup(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        answer = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return None if "error" in answer else answer


def locate(items: list[dict], *, path: str, suffixes: list[str]) -> dict[str, str] | None:
    """`{id: full path or ""}` for each `{"id", "name", "roots"}`."""
    answer = _call({"op": "locate", "items": items, "path": path, "suffixes": suffixes}, 30)
    return answer["found"] if answer else None


def probe(jobs: list[dict], *, env: dict[str, str], seconds: float) -> dict[str, dict] | None:
    """`{key: {"ok": True, "text": ...} | {"ok": False, "reason": ...}}`, all jobs at once."""
    answer = _call({"op": "probe", "jobs": jobs, "env": env, "seconds": seconds}, seconds + 10)
    return answer["results"] if answer else None
