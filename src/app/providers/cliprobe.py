"""Adapting to the external CLIs, and asking them less often.

Kriko never keeps a version table for a coding-agent CLI: a CLI is adapted to
by *asking it* (`--help`, `models`) and reading what it declares, because
`--help` is the CLI's own answer and versions do not order the way flag
support does. What was missing is that the answer lived only in process
memory. Every restart re-probed every installed CLI, and a CLI upgraded
while the app ran kept its stale answers until the app quit — a CLI that
changed was therefore *not* adapted to until someone restarted.

Both are fixed here by persisting probe answers beside the store, keyed by
the binary's stamp (mtime + size):

- an unchanged binary is never probed again, across restarts;
- a changed binary is a new key, so the next read re-probes, and every
  capability derived from the answer — declared flags, model and effort
  lists, the launch vector `command_for` builds — adapts on its own.

`ask_many` is the other half: one harness process runs every question about
one CLI at once, instead of one process per question.
"""

import json
import os
import threading
import time
from pathlib import Path

from app.loginpath import login_path
from app.providers import hostbin
from kriko.store.db import DEFAULT_STORE

#: Said to every CLI child, because we write to it in UTF-8 and read it back
#: as UTF-8 (see `app.providers.harness` for the Windows case it prevents).
CHILD_ENCODING_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

STORE_VERSION = 1

_LOCK = threading.Lock()


def stamp(executable: str) -> tuple[int, int]:
    """When this binary last changed — an update is a new cache key."""
    try:
        info = os.stat(executable)
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return (0, 0)


def store_path() -> Path:
    """Where probe answers are persisted; `KRIKO_PROBE_STORE` overrides."""
    override = os.environ.get("KRIKO_PROBE_STORE")
    if override:
        return Path(override)
    return DEFAULT_STORE.parent / "cli-probes.json"


def _load() -> dict:
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # A probe answer that cannot be persisted is still valid for this
        # process; it just will not survive a restart.
        pass


def entry(executable: str, kind: str) -> dict | None:
    """The persisted payload for `kind`, or `None` when the binary changed.

    `kind` is `"help"`, `"models"` or `"efforts"`. The payload is the whole
    per-binary record (including `at`, an epoch timestamp), so callers that
    keep their own freshness TTL (`models`) can apply it across restarts.
    """
    current = stamp(executable)
    if current == (0, 0):
        return None
    with _LOCK:
        record = _load().get("probes", {}).get(executable)
    if not isinstance(record, dict):
        return None
    if tuple(record.get("stamp") or ()) != current:
        return None
    payload = record.get(kind)
    if payload is None:
        return None
    # Each kind's own time: a `--help` recorded today must not make a model
    # list read a week ago look fresh (`models` keeps a TTL on this).
    at = record.get(f"at_{kind}", record.get("at"))
    return {"stamp": current, "at": float(at or 0.0), kind: payload}


def record(executable: str, kind: str, payload) -> None:
    """Persist one probe answer under the binary's current stamp.

    A stamp different from the stored one starts a fresh record: the old
    binary's answers are dropped with it, which is the adaptation — the next
    read of any kind finds nothing and asks the new binary.
    """
    current = stamp(executable)
    if current == (0, 0):
        return
    with _LOCK:
        data = _load()
        probes = data.setdefault("probes", {})
        if not isinstance(probes, dict):
            probes = data["probes"] = {}
        old = probes.get(executable)
        if not isinstance(old, dict) or tuple(old.get("stamp") or ()) != current:
            old = {"stamp": list(current), "at": time.time()}
        else:
            old = dict(old)
        old[kind] = payload
        old["at"] = old[f"at_{kind}"] = time.time()
        probes[executable] = old
        data["version"] = STORE_VERSION
        _save(data)


def ask_many(executable: str, questions: dict[str, list[str]], *,
             keep: int, seconds: float) -> dict[str, str] | None:
    """Ask one CLI several questions in a single harness process.

    `questions` maps a key to the arguments after the executable. Returns
    `{key: text}` for the questions that answered, or `None` when there is
    no harness binary — the caller then falls back to asking one at a time.
    A question that failed or timed out is simply absent.
    """
    jobs = [
        {"key": key, "argv": [executable, *argv], "keep": keep}
        for key, argv in questions.items()
    ]
    answered = hostbin.probe(
        jobs,
        env={"PATH": login_path(), **CHILD_ENCODING_ENV},
        seconds=seconds,
    )
    if answered is None:
        return None
    return {
        key: row["text"]
        for key, row in answered.items()
        if isinstance(row, dict) and row.get("ok") and isinstance(row.get("text"), str)
    }
