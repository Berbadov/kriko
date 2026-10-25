"""Print `requirements.lock` from the current environment.

    python tools/relock.py --write

The closure is walked rather than taken from `pip freeze`: a freeze of a
working checkout carries the pipeline extras, pytest, and whatever else got
installed along the way, and none of that belongs in the file that says what a
reader's sidecar contains. Walking from the runtime roots in
`pyproject.toml` (eight at the last count — the number is not restated here,
because a comment that counts them goes stale the next time one is added and
this one did) gives exactly the closure PyInstaller freezes.

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


#: Written into the lock by `main`, and read back out by the guard. The lock
#: is one machine's resolve — `closure()` drops what is not installed here, so
#: a Linux run pins ptyprocess and omits pywinpty, colorama and pywin32, and a
#: Windows run does the reverse. That is deliberate and the header explains it.
#: What was missing is the lock saying *which* run it was: without it the guard
#: could only ask "does this root apply on the machine running the tests", and
#: so every Windows host reported `pywinpty` as an unlocked dependency that the
#: Linux resolve had correctly left out — a fact the file did not carry,
#: asserted from the one machine that could not know it.
_RESOLVED_ON = re.compile(r"^#\s*resolved-on:\s*(\S+)\s*$", re.MULTILINE)


def resolved_on(text: str) -> str:
    """The platform whose environment produced this lock, or `sys.platform`.

    Falling back to the running platform keeps a lock written before this
    marker existed readable: it behaves exactly as it did rather than failing
    to parse. The fallback stops mattering the first time anyone regenerates.
    """
    match = _RESOLVED_ON.search(text)
    return match.group(1) if match else sys.platform


def applies_here(requirement: str, platform: str = sys.platform) -> bool:
    """Does this requirement's marker match the given platform?

    Defaults to the machine relock runs on, which is what generation wants.
    The guard passes `resolved_on(lock)` instead, because the question it is
    actually asking is whether the *lock's* platform should have pinned this.

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
    return (platform == value) if op == "==" else (platform != value)


#: The clause that decides a platform rather than a Python version. Only
#: `sys_platform` appears in this project's own requirements (see
#: `applies_here`), and only `==` names a platform a member exists on alone.
_SYS_PLATFORM = re.compile(r"sys_platform\s*==\s*['\"]([^'\"]+)['\"]")


def platform_pin(markers: set[str]) -> str:
    """`win32` when every edge agrees the member exists only there, else ''.

    `pywin32` (through `mcp`) and `pywinpty` (`pyproject.toml`) are reached only
    from a `sys_platform == 'win32'` requirement. Pinned without that fact, the
    lock could not be installed on Linux or macOS at all — pip stops on
    `pywin32==312` before anything is frozen, which is what kept the `packs` job
    and the macOS package from running. The marker is what pip would apply
    anyway, so the Windows artifact's contents do not change.

    A member reached both conditionally and unconditionally has more than one
    marker, and gets no pin: it is needed everywhere, and saying otherwise
    would drop it from a platform that needs it.
    """
    if not markers:
        return ""
    values = set()
    for marker in markers:
        found = _SYS_PLATFORM.findall(marker)
        if len(found) != 1:
            return ""
        values.add(found[0])
    return values.pop() if len(values) == 1 else ""


def resolve(roots: list[str]) -> dict[str, tuple[str | None, str]]:
    """Every distribution the roots reach: its version here, and its platform."""
    versions: dict[str, str | None] = {}
    edges: dict[str, set[str]] = {}
    queue = deque(roots)
    while queue:
        requirement = queue.popleft()
        name = name_of(requirement)
        _, _, marker = requirement.partition(";")
        edges.setdefault(name, set()).add(marker.strip())
        if name in versions:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            # Platform-only, or simply not installed on this machine. Recorded
            # as absent so a caller can say so; never invented.
            versions[name] = None
            continue
        versions[name] = dist.version
        for child in dist.requires or []:
            if "extra ==" in child:
                continue
            queue.append(child)
    return {name: (version, platform_pin(edges[name])) for name, version in versions.items()}


def closure(roots: list[str]) -> dict[str, str | None]:
    """Every distribution the roots reach, and the version installed here."""
    return {name: version for name, (version, _) in resolve(roots).items()}


def pins() -> list[str]:
    return [
        f"{name}=={version}" + (f"; sys_platform == '{platform}'" if platform else "")
        for name, (version, platform) in sorted(resolve(runtime_roots()).items())
        if version
    ]


def header() -> str:
    """The committed file's own preamble, reused verbatim.

    Rewriting the lock must not silently drop the paragraphs explaining why it
    is runtime-only and why it is not installed with `--no-deps`.
    """
    text = LOCK.read_text(encoding="utf-8")
    match = HEADER_END.search(text)
    text = text[: match.start()] if match else text
    # The previous run's marker is stripped rather than kept: it is generated,
    # not authored, and carrying it forward would leave two of them disagreeing.
    return _RESOLVED_ON.sub("", text).rstrip("\n") + "\n"


def main() -> int:
    text = header() + f"# resolved-on: {sys.platform}\n" + "\n".join(pins()) + "\n"
    if "--write" in sys.argv[1:]:
        # Written here rather than by the caller's shell, because the documented
        # `tools/relock.py > requirements.lock` truncates the very file this
        # script copies its preamble out of: the redirect is opened before the
        # process starts, so `header()` reads nothing and the paragraphs that
        # explain the file are silently lost. Writing it ourselves means the
        # preamble is read first and the file is replaced second, atomically.
        temporary = LOCK.with_suffix(".lock.tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(LOCK)
        sys.stderr.write(f"wrote {LOCK} ({len(pins())} pins)\n")
        return 0
    # stdout mode stays for inspecting a diff before deciding. Its encoding is
    # forced: the preamble is prose, and on a Windows host the console codepage
    # turns a dash into a byte that is not UTF-8, which makes the file this is
    # redirected into unreadable to the test that compares it.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
