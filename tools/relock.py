"""Print `requirements.lock` from the current environment.

    python tools/relock.py > requirements.lock

The closure is walked rather than taken from `pip freeze`: a freeze of a
working checkout carries the pipeline extras, pytest, and whatever else got
installed along the way, and none of that belongs in the file that says what a
reader's sidecar contains. Walking from the five runtime roots in
`pyproject.toml` gives exactly the closure PyInstaller freezes.

Extras are skipped — a dependency pulled in only by `package[extra]` is not
part of the runtime install — and a member that is not installed here is
dropped rather than guessed, which is what leaves colorama and pywin32 out on
a Linux resolve. See the header this prints for why that is safe.

Deliberately a script and not a test fixture: regenerating the lock is a
decision, and a lock that regenerates itself whenever the suite runs is not a
lock. `src/app/tests/test_dependencies_are_locked.py` is the half that runs
unattended, and it only ever *compares*.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
import tomllib
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"

#: Everything above the first pin in the committed file. Kept in the lock
#: rather than here so the reasoning travels with the artifact — someone
#: reading `requirements.lock` in a diff should not have to find this script.
HEADER_END = re.compile(r"^[a-z]", re.MULTILINE)


def runtime_roots() -> list[str]:
    """The `[project] dependencies`, which is the only list of roots there is.

    Read from `pyproject.toml` rather than repeated here: a sixth runtime
    dependency added there must appear in the lock without anyone remembering
    that this file exists.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return [str(dep) for dep in data["project"]["dependencies"]]


def name_of(requirement: str) -> str:
    return re.split(r"[\[<>=!;\s]", requirement.strip())[0].lower().replace("_", "-")


_MARKER = re.compile(r"sys_platform\s*(==|!=)\s*['\"]([^'\"]+)['\"]$")


def applies_here(requirement: str) -> bool:
    """Does this requirement's marker match the machine relock runs on?

    `pywinpty`/`ptyprocess` are marked with `sys_platform`, the only marker
    this project uses. A root that does not apply here cannot appear in a
    Linux-resolved lock any more than a platform-only transitive dependency
    like colorama or pywin32 can — `closure()` already drops those for the
    same reason. Without this, a root gated to the other platform reads as a
    missing pin instead of an inapplicable one.
    """
    _, _, marker = requirement.partition(";")
    marker = marker.strip()
    if not marker:
        return True
    match = _MARKER.match(marker)
    if not match:
        return True
    op, value = match.groups()
    return (sys.platform == value) if op == "==" else (sys.platform != value)


def closure(roots: list[str]) -> dict[str, str | None]:
    """Every distribution the roots reach, and the version installed here."""
    found: dict[str, str | None] = {}
    queue = deque(roots)
    while queue:
        name = name_of(queue.popleft())
        if name in found:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            # Platform-only, or simply not installed on this machine. Recorded
            # as absent so a caller can say so; never invented.
            found[name] = None
            continue
        found[name] = dist.version
        for requirement in dist.requires or []:
            if "extra ==" in requirement:
                continue
            queue.append(requirement)
    return found


def pins() -> list[str]:
    resolved = closure(runtime_roots())
    return [f"{name}=={version}" for name, version in sorted(resolved.items()) if version]


def header() -> str:
    """The committed file's own preamble, reused verbatim.

    Rewriting the lock must not silently drop the paragraphs explaining why it
    is runtime-only and why it is not installed with `--no-deps`.
    """
    text = LOCK.read_text(encoding="utf-8")
    match = HEADER_END.search(text)
    return text[: match.start()] if match else text


def main() -> int:
    sys.stdout.write(header())
    sys.stdout.write("\n".join(pins()) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
