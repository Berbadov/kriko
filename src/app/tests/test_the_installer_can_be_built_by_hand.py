"""The reader's installer has a path that does not go through GitHub.

`desktop.yml` was, until 2026-09-09, the only thing in the repository that
could produce an installer. That is a single point of failure with a vendor's
name on it, and it failed: every job on the v0.5.0 tag died in three seconds
with no runner assigned, which is what a spending cap looks like from the
inside. A tag that produces nothing is not a release, and "ship to the reader,
not to the branch" is rule 4 of the phase this repository is still in.

So the same steps live in `packaging/build_desktop.ps1`, runnable on the
Windows box that has to freeze the sidecar anyway (PyInstaller cannot
cross-compile — the workflow was never doing anything a local run could not).

That leaves the failure mode this file exists for: **two copies of a build
drift.** A step added to the workflow and not to the script means the hand-run
silently produces something the tagged build would not, and nobody finds out
until a reader opens it. The audit's rule was that every fix ships the gate
that was missing, and a second build path without a drift check is exactly the
kind of fix that passes every gate and breaks anyway.

The check is derived, never enumerated: the artifacts the workflow's `bundle`
job *names* are read off the YAML, and each must appear in the script. A new
`packaging/whatever.py` step in CI fails this the moment it lands, with no
list here to remember to update.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop.yml"
SCRIPT = ROOT / "packaging" / "build_desktop.ps1"

#: Repository files a build step invokes: the spec PyInstaller reads, the lock
#: pip installs, the smoke tests, the updater configuration.
ARTIFACT = re.compile(r"\b((?:packaging|tools)/[\w.-]+\.(?:py|spec)|requirements\.lock)\b")

#: npm scripts are the other half of the build and are not files. Matched as
#: "run <script>" and "<tool> <subcommand>" pairs rather than by name.
NPM_SCRIPT = re.compile(r"npm --prefix (\w+) (?:ci|run ([\w-]+))")

#: The two `tauri` subcommands the bundle depends on. `tauri build` producing
#: the installer and `tauri icon` producing the icons it embeds are separate
#: steps and a script can plausibly have one without the other.
TAURI_SUBCOMMAND = re.compile(r"\btauri (icon|build)\b")


def _bundle_job(text: str) -> str:
    """The `bundle:` job alone.

    The `packs:` and `release:` jobs also name `packaging/*.py`, and neither is
    part of building an installer — `publish_index.py` writes a pack index and
    `updater_manifest.py` joins three runners' artifacts, which a single
    machine has no equivalent of. Scoping here rather than allow-listing them
    below keeps this test about one thing.
    """
    start = text.index("\n    bundle:")
    end = text.index("\n    packs:", start)
    return text[start:end]


def _windows_steps(job: str) -> list[str]:
    """Every step in the job that runs on the windows leg.

    A step is skipped only if its `if:` excludes windows explicitly — the
    Linux system-deps step is the one that does. Guessing the other way (an
    allow-list of windows steps) would silently drop a new step, which is the
    drift this file is here to catch.
    """
    steps = []
    for chunk in re.split(r"\n {12}- ", job)[1:]:
        guard = re.search(r"^ *if: (.+)$", chunk, re.MULTILINE)
        if guard and "!= 'windows'" not in guard.group(1):
            condition = guard.group(1)
            if "== 'linux'" in condition or "== 'macos'" in condition:
                continue
        steps.append(chunk)
    return steps


def _uncommented(step: str) -> str:
    return "\n".join(
        line for line in step.splitlines() if not line.strip().startswith("#")
    )


@pytest.fixture(scope="module")
def workflow_build() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    return "\n".join(_uncommented(step) for step in _windows_steps(_bundle_job(text)))


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_exists_and_is_a_build(script):
    """A missing or stub script would satisfy every subset check below it."""
    assert len(script.splitlines()) > 60
    assert "tauri build" in script


def test_the_workflow_still_parses_into_steps(workflow_build):
    """A glob or slice that matches nothing passes every check under it.

    If `desktop.yml`'s shape changes enough that the `bundle:` job stops being
    found the way `_bundle_job` finds it, this fails here rather than turning
    the rest of the file green by accident.
    """
    assert ARTIFACT.findall(workflow_build), "no build artifacts found in the workflow"
    assert NPM_SCRIPT.findall(workflow_build), "no npm steps found in the workflow"


def test_every_artifact_the_release_build_names_is_named_by_the_script(
    workflow_build, script
):
    """The drift check, in the direction that matters.

    Workflow → script, not the reverse: the script may hold extra checks a
    runner does not need (`Get-Command` for the toolchain, an installer-exists
    assertion at the end), but a step the *release* build runs and the hand
    build skips means the two produce different software.
    """
    required = {m.group(1) for m in ARTIFACT.finditer(workflow_build)}
    missing = sorted(name for name in required if name not in script)
    assert missing == [], (
        f"{SCRIPT.name} does not name {missing}, which {WORKFLOW.name}'s bundle "
        "job does. A step added to CI has to be added here too, or a hand-built "
        "installer is not the one a tag produces."
    )


def test_the_script_builds_the_same_npm_surfaces(workflow_build, script):
    """`ui` and `tauri` are separate installs, and both are load-bearing.

    The prefix is checked as well as the script name because `npm run build`
    in the wrong directory is a plausible transcription error that produces a
    bundle with no frontend in it.
    """
    required = {
        (prefix, run) for prefix, run in NPM_SCRIPT.findall(workflow_build)
    }
    missing = sorted(
        f"npm --prefix {prefix} {'run ' + run if run else 'ci'}"
        for prefix, run in required
        if f"npm --prefix {prefix} {'run ' + run if run else 'ci'}" not in script
    )
    assert missing == [], f"{SCRIPT.name} is missing: {missing}"


@pytest.mark.parametrize("subcommand", ["icon", "build"])
def test_the_script_runs_both_tauri_subcommands(workflow_build, script, subcommand):
    """Derived from the workflow, then asserted on the script.

    Parametrized rather than looped so a script that bundles without
    generating icons names which half is missing.
    """
    if f"tauri {subcommand}" not in workflow_build:
        pytest.skip(f"the workflow no longer runs `tauri {subcommand}`")
    assert f"tauri {subcommand}" in script


def test_the_script_freezes_before_it_bundles(script):
    """Order is part of the build, not a detail.

    Tauri embeds whatever sits in `binaries/` at bundle time. A script that
    bundles first and freezes after produces an installer carrying the
    *previous* run's sidecar — green, silent, and wrong. Same reasoning as
    `test_the_release_workflow_verifies_the_lock_before_it_builds`.
    """
    lines = script.splitlines()
    freeze = min(i for i, line in enumerate(lines) if "PyInstaller" in line)
    place = min(i for i, line in enumerate(lines) if "binaries/kriko-sidecar" in line)
    bundle = min(
        i for i, line in enumerate(lines) if re.search(r"tauri run tauri build", line)
    )
    assert freeze < place < bundle, (freeze, place, bundle)


def test_the_script_smoke_tests_what_it_produced(script):
    """The two checks v0.2.4 did not have, in the order they have to run.

    The sidecar's handshake is checked on the frozen binary before it is
    embedded, and the shell is launched after the bundle exists. A script that
    ran either earlier would be testing something other than what it shipped.
    """
    lines = script.splitlines()
    sidecar = min(i for i, line in enumerate(lines) if "smoke_sidecar.py" in line)
    bundle = min(
        i for i, line in enumerate(lines) if re.search(r"tauri run tauri build", line)
    )
    app = min(i for i, line in enumerate(lines) if "smoke_app.py" in line)
    assert sidecar < bundle < app, (sidecar, bundle, app)


def _powershell_scripts() -> list[Path]:
    """Tracked `.ps1` files -- the ones this repository is responsible for.

    `ROOT.glob("**/*.ps1")` was the first version and it reached
    `.venv/bin/activate.ps1`, which virtualenv wrote and nobody here can fix.
    Worse, that set changes with whether a virtualenv happens to be sitting in
    the checkout, so the gate would have been machine-dependent. `git ls-files`
    is the honest answer to "what did we author", and is how
    `test_repo_invariants.py` asks the same question.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.ps1"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    return sorted(ROOT / raw.decode() for raw in tracked if raw)


def test_there_are_powershell_scripts_to_check():
    """A listing that matches nothing passes every check under it."""
    assert _powershell_scripts(), "no tracked .ps1 files found"


@pytest.mark.parametrize("ps1", _powershell_scripts(), ids=lambda p: p.name)
def test_a_powershell_script_is_ascii_only(ps1: Path):
    """Windows PowerShell 5.1 decodes a BOM-less .ps1 as ANSI, not UTF-8.

    Found by running the thing. `build_desktop.ps1` was written with em-dashes
    in its comments, which is fine in every editor and fine under `pwsh` 7 --
    and a parse error under `powershell` 5.1, which is what a stock Windows box
    actually has. 5.1 reads a script with no BOM using the system codepage
    (1254 on the machine this first ran on), so each em-dash became three
    mojibake bytes, one of them a quote character, and the *next* string
    literal was the thing that failed. Six cascading parse errors pointing at
    lines 62, 85, 86, 88 and 157, none of them the line with the em-dash on it.

    ASCII rather than a BOM: a BOM fixes 5.1 and is invisible in a diff, so the
    next person writes the same bug and the file quietly needs re-saving in the
    right encoding forever. ASCII fails here instead, in a test naming the
    character.

    Not a style rule -- a build script that cannot be parsed produces no
    installer, and B81 exists because the alternative path to one was down.
    """
    raw = ps1.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        f"{ps1.name} starts with a UTF-8 BOM. Keep it ASCII instead so the "
        "constraint is visible in a diff."
    )
    offenders = [
        (n, line)
        for n, line in enumerate(raw.decode("utf-8").splitlines(), start=1)
        if any(ord(ch) > 127 for ch in line)
    ]
    assert offenders == [], (
        f"{ps1.name} has non-ASCII characters at lines "
        f"{[n for n, _ in offenders]}. Windows PowerShell 5.1 reads this file "
        "with the machine's ANSI codepage and will fail to parse it. Use "
        "plain ASCII: -- for an em-dash, ... for an ellipsis."
    )
