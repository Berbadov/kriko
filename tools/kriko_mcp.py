#!/usr/bin/env python3
"""Start Kriko's MCP server with whichever engine this machine has.

`.mcp.json` used to name `.venv/bin/python`, relative to the repository. That
is one machine's layout: a cloud session, a git worktree (its venv lives in the
main checkout), a reader who installed the app and never made a venv, and
Windows (`Scripts\\python.exe`) all failed the same way, with a spawn error and
nothing on stdout for the client to read. This script is the one command every
client can name; it looks for an engine and becomes it.

Only the standard library, so it runs under any `python3` before there is an
engine to import. It prints nothing on stdout (that is the protocol's) and
explains a failure on stderr.

Where it looks, first match wins:

1. `KRIKO_PYTHON`: an interpreter the reader chose (the desktop shell's own
   variable, so one setting serves both).
2. A virtualenv in this checkout, then in the main checkout this worktree
   belongs to.
3. The interpreter running this script, when it can already import the engine.
4. An installed app's `kriko-sidecar` next to the usual install locations, or
   on `PATH`.

Pass `--store PATH` and any other sidecar flag through unchanged:
`kriko_mcp.py --store /tmp/k.sqlite`, or `--mcp-http` for a local URL.
`--print` says which engine would start and exits, for a person asking why.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PROBE = "import app.sidecar, mcp"
_VENV_PYTHONS = (".venv/bin/python", ".venv/Scripts/python.exe")


def _main_checkout(root: Path) -> Path | None:
    """The main checkout a git worktree belongs to, or None.

    A worktree's `.git` is a file saying `gitdir: <main>/.git/worktrees/<name>`.
    Read as text, not through `git`, so this works with no git on `PATH`.
    """
    marker = root / ".git"
    if not marker.is_file():
        return None
    try:
        line = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    # <main>/.git/worktrees/<name> -> <main>
    for parent in gitdir.parents:
        if parent.name == ".git":
            return parent.parent
    return None


def _app_locations(environ: dict[str, str], platform: str) -> list[Path]:
    """Where an installed app keeps its engine, per platform. A closed set."""
    name = "kriko-sidecar.exe" if platform == "win32" else "kriko-sidecar"
    home = Path(environ.get("USERPROFILE") or environ.get("HOME") or "~").expanduser()
    found: list[Path] = []
    if platform == "win32":
        local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        for base in (local / "Kriko", local / "Programs" / "Kriko",
                     Path(environ.get("ProgramFiles") or r"C:\Program Files") / "Kriko"):
            found.append(base / name)
    elif platform == "darwin":
        for base in (Path("/Applications/Kriko.app/Contents/MacOS"),
                     home / "Applications/Kriko.app/Contents/MacOS"):
            found.append(base / name)
    else:
        for base in (home / ".local/share/kriko", Path("/opt/kriko"), Path("/usr/lib/kriko")):
            found.append(base / name)
    return found


def can_import_engine(python: str, src: Path | None) -> bool:
    """Whether `python` can import the engine and the MCP package.

    The probe runs the real import, because "a venv exists" is the assumption
    that failed: a venv without the project installed is as dead as none.
    """
    env = dict(os.environ)
    if src is not None and src.is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            [str(src), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
    try:
        done = subprocess.run([python, "-c", _PROBE], env=env, timeout=60,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def find_engine(
    root: Path = ROOT,
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    probe: Callable[[str, Path | None], bool] = can_import_engine,
    which: Callable[[str], str | None] = shutil.which,
    executable: str | None = None,
) -> tuple[list[str], dict[str, str], str]:
    """(argv prefix, extra environment, how it was found) or raise LookupError.

    The argv prefix is everything before the flags the caller passes on.
    """
    environ = dict(os.environ if environ is None else environ)
    platform = platform or sys.platform
    executable = executable if executable is not None else sys.executable
    src = root / "src"
    src_env = {"PYTHONPATH": str(src)} if (src / "app").is_dir() else {}
    tried: list[str] = []

    def interpreter(path: str, how: str, extra: dict[str, str]):
        if probe(path, src if extra else None):
            return [path, "-m", "app.sidecar"], extra, how
        tried.append(f"{how}: {path} cannot import the engine")
        return None

    chosen = environ.get("KRIKO_PYTHON", "").strip()
    if chosen:
        hit = interpreter(chosen, "KRIKO_PYTHON", src_env)
        if hit:
            return hit
    for base, label in ((root, "this checkout's venv"),
                        (_main_checkout(root), "the main checkout's venv")):
        if base is None:
            continue
        for rel in _VENV_PYTHONS:
            candidate = base / rel
            if candidate.is_file():
                hit = interpreter(str(candidate), label, src_env)
                if hit:
                    return hit
    if executable:
        hit = interpreter(executable, "the interpreter running this script", src_env)
        if hit:
            return hit
    name = "kriko-sidecar.exe" if platform == "win32" else "kriko-sidecar"
    candidates: Iterable[str | None] = [
        which(name), *(str(p) if p.is_file() else None
                       for p in _app_locations(environ, platform))]
    for candidate in candidates:
        if candidate:
            return [candidate], {}, "an installed Kriko"
    tried.append(f"no {name} on PATH or in the usual install folders")
    raise LookupError("; ".join(tried) or "nothing to try")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    show = "--print" in args
    args = [a for a in args if a != "--print"]
    try:
        prefix, extra, how = find_engine()
    except LookupError as error:
        print("kriko mcp: no Kriko engine found.\n"
              f"  tried: {error}\n"
              "  Install the app, or run tools/setup.sh in a checkout, or set "
              "KRIKO_PYTHON to an interpreter that has Kriko installed.",
              file=sys.stderr)
        return 1
    argv_full = [*prefix, "--mcp", *args]
    if show:
        print(f"{how}: {' '.join(argv_full)}", file=sys.stderr)
        return 0
    env = {**os.environ, **extra}
    if sys.platform == "win32":
        # No exec on Windows: a child with the same stdio, and its exit code.
        return subprocess.call(argv_full, env=env)
    os.execvpe(argv_full[0], argv_full, env)
    return 0  # unreachable: exec replaced this process


if __name__ == "__main__":
    raise SystemExit(main())
