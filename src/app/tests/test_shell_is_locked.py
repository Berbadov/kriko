"""The desktop app builds from a crate graph somebody committed.

B53. A Rust app whose lockfile is not in the repository resolves whatever
crates.io holds that minute, on every build. That is not a theoretical
exposure: the last shell (Tauri) opened on one build and panicked before its
first window on another, four hours later, from an identical tree, because a
plugin's tolerance for a missing config section changed underneath it. Nothing
in the tree moved, and the artifact stopped working.

`kriko-gpui/Cargo.lock` is the fix; this file is the half that keeps it true,
and it runs with no Rust toolchain installed, which is the point: the
invariant has to hold on every machine that touches the tree.

Three things it asks, and each is a way the lock can be present and still not
do its job:

* **Every declared crate is in it, at the major that was declared.** A lock
  that lags `Cargo.toml` describes a graph nobody builds.
* **It covers the platform we ship to.** Cargo folds every target into the one
  file. The Windows crates are what the installer is made of; if they stop
  appearing, the lock was produced some other way and pins nothing for the
  readers who download it.
* **Everything comes from the registry.** A `git` or `path` source resolves to
  a moving branch or to a directory that exists on one person's disk.

And the fourth, which is the same rule `test_dependencies_are_locked.py`
carries for Python: both build paths (`desktop.yml` and `kriko-gpui/package.ps1`)
have to *verify* the lock before they build. Cargo already uses a committed
lock; what it also does, silently, is rewrite one that has fallen behind, and
then the tagged release is not the graph anybody reviewed. `--locked` makes
that a red job. `test_the_lock_is_verified_in_both_build_paths.py` holds the
ordering; the `--locked` flag itself is asserted here for the workflow.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CRATE = ROOT / "kriko-gpui"
LOCK = CRATE / "Cargo.lock"
MANIFEST = CRATE / "Cargo.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"

REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"

#: Crates that can only come from a resolve that considered Windows, the
#: platform the installer is for. Named by *family* rather than exact version,
#: because these move with the ecosystem: the invariant is that the family is
#: represented, not which release of it.
FOREIGN_TARGETS = {
    "windows": ("windows-sys", "windows_x86_64_msvc"),
}


def _declared() -> dict[str, str]:
    """The crate's own dependencies, both kinds, as name -> version string.

    Build dependencies count (`winresource` runs at compile time and writes
    the icon into the binary), and so do the per-target tables
    (`cfg(windows)` holds the tray and the window handle).
    """
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    tables = [manifest.get(t, {}) for t in ("dependencies", "build-dependencies")]
    tables += [
        target.get("dependencies", {}) for target in manifest.get("target", {}).values()
    ]
    declared = {}
    for table in tables:
        for name, spec in table.items():
            version = spec if isinstance(spec, str) else spec.get("version")
            if version:
                declared[name] = version
    return declared


@pytest.fixture(scope="module")
def locked() -> dict[str, list[str]]:
    """name -> every version of it in the lock (a graph carries duplicates)."""
    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    versions: dict[str, list[str]] = {}
    for package in data["package"]:
        versions.setdefault(package["name"], []).append(package["version"])
    return versions


def test_the_app_has_a_lockfile_at_all(locked):
    """The row this file closes, stated as the assertion that would have failed.

    The count matters as much as the existence: a lock holding four entries
    would satisfy every name check below it while pinning none of the graph
    those four pull in.
    """
    assert LOCK.is_file(), f"no committed lockfile at {LOCK}"
    assert len(locked) > 300, (
        f"{LOCK} holds {len(locked)} packages, which is too few to be the app's "
        "graph — regenerate with `cargo generate-lockfile` in kriko-gpui/"
    )


@pytest.mark.parametrize("crate", sorted(_declared()))
def test_every_declared_crate_is_locked_at_the_declared_major(crate, locked):
    """One case per crate, so the failure names the crate rather than a count."""
    wanted = _declared()[crate]
    assert crate in locked, f"{crate} is in Cargo.toml and not in Cargo.lock"
    major = wanted.lstrip("^~=><").split(".")[0]
    majors = {version.split(".")[0] for version in locked[crate]}
    assert major in majors, (
        f"Cargo.toml wants {crate} {wanted} and the lock has {locked[crate]}. "
        "The lock is behind the manifest, so it describes a graph nobody builds."
    )


@pytest.mark.parametrize("platform", sorted(FOREIGN_TARGETS))
def test_the_lock_covers_the_platforms_we_ship_to(platform, locked):
    """The hazard of generating the lock wherever it happens to be generated.

    Cargo resolves every target into one file. The readers who download the
    installer are on Windows; if the family disappears from here, the lock
    stopped being produced by `cargo generate-lockfile` and stopped covering
    them.
    """
    missing = [name for name in FOREIGN_TARGETS[platform] if name not in locked]
    assert missing == [], (
        f"no {platform} crates in the lock ({missing} absent), so it pins "
        "nothing for a platform we ship an installer for"
    )


def test_nothing_resolves_to_a_moving_source():
    """A `git` dependency pins a branch; a `path` one pins somebody's disk.

    Only the crate itself may have no source — that is what "this is the local
    package" means in a lockfile.
    """
    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    ours = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["package"]["name"]
    strange = sorted(
        f"{package['name']} <- {package.get('source', 'no source')}"
        for package in data["package"]
        if package["name"] != ours and package.get("source") != REGISTRY
    )
    assert strange == [], f"not resolved from crates.io: {strange}"


def test_the_release_workflow_verifies_the_lock_before_it_builds():
    """A lock nothing reads is a document, not a gate — and order matters.

    Cargo uses a committed lock without being asked; `--locked` is what stops
    it *rewriting* one that has fallen behind the manifest. Checked before the
    build step, because a rewrite during the build is the case where the
    installer that ships is not the graph anyone reviewed.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    verify = [i for i, line in enumerate(lines) if "--locked" in line]
    build = [i for i, line in enumerate(lines) if re.search(r"\bcargo\b.*\b(build|wix)\b", line)]
    assert verify, "desktop.yml never verifies the crate lock (`cargo … --locked`)"
    assert build, "desktop.yml no longer builds the app — this test is stale"
    assert min(verify) < min(build), (
        "the --locked check runs after the build, which is too late: cargo will "
        "already have rewritten the lock it was supposed to be held to"
    )
