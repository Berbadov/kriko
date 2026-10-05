"""One release, one number, in the places nothing links together.

The version lives in `pyproject.toml`, `kriko-gpui/Cargo.toml` and the
`kriko-gpui` entry of `kriko-gpui/Cargo.lock`, and `python tools/bump.py
<version>` sets all three. Cargo and setuptools each read their own file, so
nothing in the toolchain notices a disagreement: it surfaces as an installer
whose name is one version and whose contents are another. The fourth place is
the installed distribution `/api/health` reports, checked last.

There is no self-updater in 1.0, so a wrong number no longer makes an app offer
itself its own update forever; it makes the About page and the installer name
lie, which is the same defect with a quieter symptom.
"""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CRATE = REPO / "kriko-gpui"


def _locked_version() -> str:
    text = (CRATE / "Cargo.lock").read_text(encoding="utf-8")
    found = re.search(r'name = "kriko-gpui"\r?\nversion = "([^"]+)"', text)
    assert found, "Cargo.lock has no kriko-gpui entry"
    return found.group(1)


def test_the_version_strings_agree():
    declared = {
        "pyproject.toml": tomllib.loads(
            (REPO / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"],
        "kriko-gpui/Cargo.toml": tomllib.loads(
            (CRATE / "Cargo.toml").read_text(encoding="utf-8")
        )["package"]["version"],
        "kriko-gpui/Cargo.lock": _locked_version(),
    }
    assert len(set(declared.values())) == 1, (
        f"the version differs between files: {declared}. "
        "`python tools/bump.py <version>` sets all of them."
    )
    assert re.fullmatch(r"\d+\.\d+\.\d+", next(iter(declared.values())))


def test_the_bump_tool_covers_exactly_these_files():
    """If a place is added to the tree and not to the tool, a bump leaves it
    behind; if the tool names a file that is gone, a bump fails halfway."""
    import sys

    sys.path.insert(0, str(REPO / "tools"))
    import bump

    assert {str(p).replace("\\", "/") for p, _ in bump.PLACES} == {
        "pyproject.toml",
        "kriko-gpui/Cargo.toml",
        "kriko-gpui/Cargo.lock",
    }
    for path, pattern in bump.PLACES:
        assert pattern.search((REPO / path).read_text(encoding="utf-8")), path


def test_the_version_the_app_reports_is_the_version_the_tree_says():
    """The fourth place the number can be wrong, and the only live one.

    `/api/health` answers from the *installed* distribution's metadata, written
    at install time, so a stale editable install reports a version the tree has
    not been at for months. Failing here means the environment is stale, not
    the tree: reinstall.
    """
    from app.version import app_version

    declared = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    assert app_version() == declared, (
        f"the installed distribution says {app_version()}, pyproject says "
        f"{declared}: reinstall (`pip install -e .`) before cutting a release"
    )
