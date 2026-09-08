"""The installer's Python closure is pinned, and the pins are the ones we test.

B57, the Python half. Three npm surfaces were already locked and `desktop.yml`
already used `npm ci` for all of them; the fourth was `pip install -e "."`,
which resolves whatever PyPI holds the minute the job runs. The evidence that
this matters is not hypothetical — v0.2.1 opened and v0.2.4, built four hours
later from an identical tree, panicked on a config both shipped, because a
crate's tolerance changed underneath. Nothing made Python safer; it just had
not bitten yet.

A lockfile alone is only half a gate, though. The half that actually catches
things is this: **the lock must agree with the environment the suite passed
in.** A pin nobody runs against is a guess with a version number on it, and a
lock that drifts from the working tree fails on a release machine at the worst
possible moment — during a release.

So there are two directions here, and both matter:

* every runtime root in `pyproject.toml` reaches the lock (a sixth dependency
  cannot be added without landing here), and
* every pin in the lock matches what is installed (the lock cannot go stale
  while the suite stays green).

The pipeline and dev extras are deliberately *not* locked: they run on an
authoring machine, and pinning them would make a research-tool bump a change
to the artifact a reader downloads.
"""

import importlib.metadata as md
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_relock():
    """`tools/` is scripts, not a package — loaded by path rather than import.

    Making it importable would mean an `__init__.py` and a sys.path entry for
    a directory that holds one-off operator scripts, and `pytest.ini` names
    the test roots explicitly for a reason.
    """
    spec = importlib.util.spec_from_file_location("relock", ROOT / "tools" / "relock.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relock = _load_relock()
LOCK = ROOT / "requirements.lock"


def parse(text: str) -> dict[str, str]:
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition("==")
        pins[name] = version
    return pins


@pytest.fixture(scope="module")
def locked() -> dict[str, str]:
    return parse(LOCK.read_text(encoding="utf-8"))


def test_the_lock_exists_and_is_pins(locked):
    """An empty or missing lock would satisfy every comparison below it."""
    assert len(locked) > 20, f"{LOCK} holds {len(locked)} pins"
    assert all(version for version in locked.values())


def test_every_runtime_root_is_locked(locked):
    """Read off `pyproject.toml`, so a new dependency cannot skip the lock."""
    roots = [relock.name_of(dep) for dep in relock.runtime_roots()]
    assert roots, "pyproject declares no runtime dependencies"
    assert [root for root in roots if root not in locked] == []


def test_the_lock_matches_what_the_suite_ran_against(locked):
    """The direction that catches drift.

    A pin that no longer matches the installed version means the tests are
    green against one closure and the installer ships another. Regenerate with
    `python tools/relock.py > requirements.lock` and read the diff — a version
    moving is a fact worth one line in a commit message.
    """
    drifted = {}
    for name, pinned in locked.items():
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            # Not an error: the lock is shared by Linux and Windows builds and
            # a member can be absent here. It is still pinned for the build
            # that does install it.
            continue
        if installed != pinned:
            drifted[name] = (pinned, installed)
    assert drifted == {}, (
        "requirements.lock disagrees with this environment (pinned, installed): "
        f"{drifted}. Run `python tools/relock.py > requirements.lock`."
    )


def test_the_lock_holds_the_runtime_closure_and_not_the_extras(locked):
    """No pytest, no research tooling — this file describes a reader's sidecar.

    Derived from the extras' own declarations rather than a list of names, so
    a tool added to `[pipeline]` tomorrow is covered without an edit here.
    """
    import tomllib

    data = tomllib.loads((relock.ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    named = {relock.name_of(dep) for group in extras.values() for dep in group}
    # httpx is in the closure legitimately — mcp requires it — so the check is
    # "declared *only* as an extra", which is what the closure walk decides.
    closure = {name for name, version in relock.closure(relock.runtime_roots()).items() if version}
    leaked = sorted(name for name in named & set(locked) if name not in closure)
    assert leaked == [], f"extras-only packages pinned in the runtime lock: {leaked}"


def _workflows() -> list[Path]:
    return sorted((relock.ROOT / ".github" / "workflows").glob("*.yml"))


def test_there_are_workflows_to_check():
    """A glob that matches nothing passes every check under it."""
    assert len(_workflows()) >= 2, [p.name for p in _workflows()]


@pytest.mark.parametrize("workflow", _workflows(), ids=lambda p: p.name)
def test_every_workflow_that_installs_python_installs_the_lock(workflow: Path):
    """A lock nothing reads is a document, not a gate — in *every* job.

    This started as a check on `desktop.yml` alone, on the reasoning that it is
    the only job producing the artifact a reader double-clicks. That reasoning
    was right about the artifact and wrong about the gate, and the drift check
    above proved it within the hour: `ci.yml` installed `-e ".[dev,pipeline]"`,
    resolved whatever PyPI held that minute, and went red against a lock built
    from a different closure. Which is the correct outcome — the suite's whole
    claim is that it passed against the closure the installer freezes, and a
    job that resolves freely cannot make that claim.

    So the check is per workflow and derived from the directory, because the
    thing that actually failed here was a *second* workflow installing Python
    with nobody remembering this rule applied to it. A third one tomorrow is
    covered the day it lands.
    """
    # Comments are skipped, and that is not a nicety: `ci.yml` explains the
    # stale-bundle check with the words "pip install kriko" in prose, which the
    # first version of this read as an unlocked install.
    installs = [
        line.strip()
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if "pip install" in line
        and not line.strip().startswith("#")
        and "--upgrade pip" not in line
    ]
    if not installs:
        pytest.skip(f"{workflow.name} installs no Python")
    unlocked = [line for line in installs if "requirements.lock" not in line]
    assert unlocked == [], (
        f"{workflow.name} installs Python without the lock: {unlocked}. "
        "Extras may be unpinned — they never reach a reader — but the runtime "
        "closure has to be the one the artifact ships."
    )
