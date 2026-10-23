"""Set the version, in the five places it lives.

    python tools/bump.py 0.8.1
    python tools/bump.py --show

**Why a script for a `sed`.** The app version is in four build files:
`pyproject.toml`, `kriko-ui/src-tauri/Cargo.toml`, `kriko-ui/package.json` and
the `kriko` entry of `kriko-ui/src-tauri/Cargo.lock`. `test_the_version_strings_agree` fails if they
disagree. README's badge and download filenames, and kriko.cc's download button,
are updated alongside them.
That test is the reason bumping by hand mostly works and is exactly
the wrong shape: it tells you afterwards, once, that you missed one.

The fourth place is not a file in the tree at all. `app.version.app_version()`
reads the *installed* distribution's metadata, which is what `/api/health`
reports, so a tree at 0.8.1 with a 0.8.0 editable install serves 0.8.0, and
`test_the_version_the_app_reports_is_the_version_the_tree_says` goes red for a
reason that is about your `.venv` rather than about your change. That one needs
a reinstall, not an edit, which is why a `sed` could never have finished the
job. This says so, and tells you the command.

Deliberately not a git tag and not a commit. Tagging is a release decision, and
a tool that tags as a side effect of an edit is a tool that cuts releases by
accident.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Each file, and the pattern whose one capture group is the version. Written
#: as anchored patterns rather than a bare string replace, because "0.8.0"
#: appears in prose in half these files and a blind swap would rewrite a
#: sentence about what happened in 0.8.0.
PLACES = (
    (Path("pyproject.toml"), re.compile(r'^(version = ")([^"]+)(")', re.M)),
    (Path("kriko-ui/src-tauri/Cargo.toml"), re.compile(r'^(version = ")([^"]+)(")', re.M)),
    # The window's own package file. `tauri.conf.json` carries no version of its
    # own: Tauri reads the crate's.
    (Path("kriko-ui/package.json"), re.compile(r'^(  "version": ")([^"]+)(")', re.M)),
    # The lock, and it is not bookkeeping. `package.ps1` and `desktop.yml` run
    # `cargo metadata --locked`, so a lock that has fallen behind Cargo.toml is
    # a red build rather than a silent rewrite, which means a stale entry here
    # does not disagree quietly, it *stops the build*.
    #
    # Anchored on the crate's own entry: a lock is thousands of lines of
    # dependency versions and every one of them must be left alone.
    (Path("kriko-ui/src-tauri/Cargo.lock"),
     re.compile(r'(name = "kriko"\r?\nversion = ")([^"]+)(")')),
)

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
README_VERSION = re.compile(r"(badge/version-)(\d+\.\d+\.\d+)(-)")
README_DOWNLOAD = re.compile(
    r"(kriko-)(\d+\.\d+\.\d+)"
    r"(-(?:x86_64-setup\.exe|win64-portable\.zip|macos-(?:arm64|x86_64)(?:-portable\.zip|\.dmg)))")

#: The website's download button. kriko.cc hands the reader the installer file
#: itself, not the release page it sits on, so the version is in the asset's own
#: name and has to move with the tree the way the README's filenames do. The
#: Turkish page is the renderer's copy of the same anchor and is checked too: a
#: release that moved one and not the other is a dead button in one language.
SITE_DOWNLOAD = re.compile(
    r"(releases/latest/download/kriko-)(\d+\.\d+\.\d+)(-x86_64-setup\.exe)")
SITE_PAGES = (Path("site/index.html"), Path("site/tr/index.html"))


def current() -> dict[Path, str]:
    found = {}
    for path, pattern in PLACES:
        text = (ROOT / path).read_text(encoding="utf-8")
        match = pattern.search(text)
        if match is None:
            raise SystemExit(f"no version line found in {path}")
        found[path] = match.group(2)
    return found


def installed() -> str:
    """What `/api/health` would report from this environment.

    The empty string means "not installed here" — a fresh clone, a CI
    runner before its first `pip install -e .`, any interpreter the app
    was never installed into. That is absence, not disagreement, and the
    `--strict` check below reads it as such: it fails a *stale* install
    (an editable 0.7.11 behind a 0.8.0 tree), never a missing one.
    """
    try:
        from app.version import app_version
    except ImportError:
        return ""
    return app_version()


def show(strict: bool = False) -> int:
    found = current()
    readme = README_VERSION.search((ROOT / "README.md").read_text(encoding="utf-8"))
    if readme is None:
        print("README.md has no version badge")
        return 1
    found[Path("README.md")] = readme.group(2)
    downloads = README_DOWNLOAD.findall((ROOT / "README.md").read_text(encoding="utf-8"))
    if not downloads or any(version != readme.group(2) for _, version, _ in downloads):
        print("README.md download filenames disagree with its version badge")
        return 1
    # The website's button names the installer file, so it is one more place the
    # version lives. Checked here rather than only at bump time: the gate runs
    # `--show --strict`, and so does the release job before it publishes.
    for page in SITE_PAGES:
        full = ROOT / page
        if not full.exists():
            continue
        link = SITE_DOWNLOAD.search(full.read_text(encoding="utf-8"))
        if link is None:
            print(f"{page} has no direct installer download link")
            return 1
        if link.group(2) != readme.group(2):
            print(f"{page} downloads {link.group(2)} while the tree is {readme.group(2)}")
            return 1
        found[page] = link.group(2)
    width = max(len(str(p)) for p in found)
    for path, version in found.items():
        print(f"{str(path):<{width}}  {version}")
    print(f"{'installed distribution':<{width}}  {installed()}")
    values = set(found.values())
    if len(values) > 1:
        print("\nthese disagree — `python tools/bump.py <version>` sets them all")
        return 1
    # The installed distribution is the fourth string, and the one the reader
    # is shown: `/api/health` and `app_version()` read it rather than the
    # tree. An editable install left behind by an earlier bump is how a
    # 0.8.7 checkout reported itself as 0.7.11 for days. Absent is fine --
    # a fresh clone has not installed anything yet, and that is not a lie.
    #
    # Only under `--strict`, and the reason is a build that failed on this in
    # the field: `kriko-ui/package.ps1` runs the plain check as a
    # pre-flight, *before* its own `pip install -e .`, so failing here would
    # refuse the build over a state that same build repairs a step later -- a
    # guard blocking the thing that fixes what it is complaining about. The
    # gate wants the check (a stale install serves the wrong version all day);
    # a pre-flight that precedes the install does not.
    here = installed()
    if strict and here and here not in values:
        print(
            f"\nthe tree says {values.pop()} and the installed distribution says"
            f" {here} — /api/health will report the installed one:\n"
            "    tools/setup.sh          (or: pip install -e .)"
        )
        return 1
    return 0


def bump(version: str, reset: bool = False) -> int:
    if not SEMVER.match(version):
        raise SystemExit(f"{version!r} is not X.Y.Z")
    previous = set(current().values())
    if len(previous) != 1:
        raise SystemExit("version files disagree; reconcile them before bumping")
    old = previous.pop()
    # A reset is an explicit product decision, not an accident the tool
    # quietly allows: going backwards is refused unless the caller names it,
    # so a mistyped `1.8.1` as `1.7.1` still stops here. Uniqueness against
    # the published inventory is the release step's own check.
    if tuple(map(int, version.split("."))) <= tuple(map(int, old.split("."))) and not reset:
        raise SystemExit(
            f"{version} must be newer than {old}; published versions are immutable. "
            "If this is the deliberate version reset, pass --reset."
        )
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    readme, count = README_VERSION.subn(rf"\g<1>{version}\g<3>", readme)
    if count != 1:
        raise SystemExit("README.md must have exactly one version badge")
    readme = README_DOWNLOAD.sub(rf"\g<1>{version}\g<3>", readme)
    for page in SITE_PAGES:
        full = ROOT / page
        if not full.exists():
            continue
        text = full.read_text(encoding="utf-8")
        text, count = SITE_DOWNLOAD.subn(rf"\g<1>{version}\g<3>", text)
        if count != 1:
            raise SystemExit(f"{page} must link the installer download exactly once")
        # Bytes, like the version files above: the newlines stay the file's own.
        full.write_bytes(text.encode("utf-8"))
        print(f"{page} -> {version}")
    for path, pattern in PLACES:
        full = ROOT / path
        text = full.read_text(encoding="utf-8")
        # count=1: the *first* version line is the project's own. A Cargo.toml
        # names its dependencies' versions too, and this must not touch them.
        new, count = pattern.subn(rf"\g<1>{version}\g<3>", text, count=1)
        if count != 1:
            raise SystemExit(f"no version line found in {path}")
        # Bytes, keeping whatever newlines the file already had. `write_text`
        # on Windows translates "\n" into "\r\n", so setting one version line
        # rewrote all 382 of pyproject.toml's and left five files dirty in a
        # diff nobody could read — the same defect `aa795e6` fixed for
        # the old shell's config, here in the one tool that touches every version
        # string at once. `read_text` already normalised the newlines it
        # returned, so writing the bytes back preserves the file instead of
        # converting it.
        full.write_bytes(new.encode("utf-8"))
        print(f"{path} -> {version}")
    readme_path.write_bytes(readme.encode("utf-8"))
    print(f"README.md -> {version} (add the reader-visible release notes too)")

    if installed() != version:
        print(
            f"\nThe installed distribution still says {installed()}, so /api/health "
            f"and the version test will too. Re-install it:\n"
            f"    tools/setup.sh          (or: .venv/bin/pip install -e .)"
        )
    tracked = subprocess.run(
        ["git", "diff", "--name-only"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    if tracked:
        print("\nchanged: " + ", ".join(tracked))
    print("\nNot committed and not tagged — both are yours to decide.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tools/bump.py", description=__doc__.split("\n")[0])
    parser.add_argument("version", nargs="?", help="the new version, as X.Y.Z")
    parser.add_argument("--show", action="store_true", help="print every place and stop")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail when the installed distribution is not the tree",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="allow going backwards: the deliberate version reset",
    )
    args = parser.parse_args(argv)
    if args.show or not args.version:
        return show(strict=args.strict)
    return bump(args.version, reset=args.reset)


if __name__ == "__main__":
    sys.exit(main())
