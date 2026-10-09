"""The `PATH` a fresh login would have, as opposed to the one this process got.

A desktop app started from the Start menu inherits the `PATH` that existed when
the reader logged in. A coding-agent CLI installed afterwards (an npm global, a
pip `--user` script, a winget package) put itself on the *registry's* `PATH`
and on the disk, but never on this process's, so `which("claude")` answered
`None` until the reader signed out and in again, and the app said no agent was
installed. Nothing about that depends on where the CLI lives, so the fix is
not a longer list of folders: it is to read the same two registry values the
next login will read.

Windows only; elsewhere the process `PATH` is the answer.
"""

from __future__ import annotations

import os
import sys

#: Where Windows keeps the machine's and the user's `PATH`, in the order a
#: login composes them (machine first).
_MACHINE_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_USER_KEY = r"Environment"


def _registry_path_values() -> list[str]:
    """The raw `Path` values, machine then user. Empty where there is no registry."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - win32 always has it
        return []
    values: list[str] = []
    for hive, subkey in ((winreg.HKEY_LOCAL_MACHINE, _MACHINE_KEY), (winreg.HKEY_CURRENT_USER, _USER_KEY)):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                raw, _kind = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if isinstance(raw, str) and raw:
            values.append(raw)
    return values


def _split(value: str) -> list[str]:
    # `%USERPROFILE%\.local\bin` is stored unexpanded (REG_EXPAND_SZ)
    return [os.path.expandvars(part.strip().strip('"')) for part in value.split(os.pathsep) if part.strip()]


def login_path(process_path: str | None = None) -> str:
    """This process's `PATH`, then every folder a fresh login would add.

    The process's own entries stay first: they are what the reader's shell and
    any wrapper asked for, and a folder both lists keeps its earlier place.
    """
    current = os.environ.get("PATH", "") if process_path is None else process_path
    seen: set[str] = set()
    folders: list[str] = []
    for folder in [*current.split(os.pathsep), *(p for raw in _registry_path_values() for p in _split(raw))]:
        folder = folder.strip()
        if not folder:
            continue
        key = os.path.normcase(os.path.normpath(folder))
        if key in seen:
            continue
        seen.add(key)
        folders.append(folder)
    return os.pathsep.join(folders)


def child_env(base: dict[str, str] | None = None, *, extra_dirs: tuple[str, ...] = ()) -> dict[str, str]:
    """`base` (default: the environment) with the login `PATH`, and any `extra_dirs` first.

    A CLI that is a script (`claude` is node, `vibe` is Python) finds its own
    runtime through `PATH`, so the process an agent runs in needs the same
    fresh view the lookup used, or the agent is found and then fails to start.
    """
    env = dict(os.environ if base is None else base)
    env["PATH"] = login_path(env.get("PATH", ""))
    wanted = [d for d in extra_dirs if d]
    if wanted:
        env["PATH"] = os.pathsep.join([*wanted, env["PATH"]])
    return env
