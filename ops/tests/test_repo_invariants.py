"""Structural invariants — the rules that no unit test would otherwise catch.

These guard the shape of the repository rather than the behaviour of any one
module. Both encode a regression that actually happened, so each failure
message names the fix rather than just the fact.
"""

import re
from configparser import ConfigParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# A cross-package import at the start of a line, with or without indentation:
# both `from backend.x import y` and `import backend.x as z`, top-level or
# deferred inside a function body.
def _imports_of(package: str, tree: Path) -> list[str]:
    pattern = re.compile(rf"^\s*(?:from|import)\s+{package}\b")
    hits = []
    for path in sorted(tree.rglob("*.py")):
        if "/tests/" in path.as_posix() or "__pycache__" in path.as_posix():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.match(line):
                hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    return hits


def test_knowledge_never_imports_from_the_layers_above_it():
    """knowledge/ is layer 1 — it may not reach up into backend/ or ops/.

    Before 2026-08-21 it did, 14 times, 11 of them written inside function
    bodies to dodge the resulting import cycle. See the layering principle in
    CLAUDE.md. If this fails, the module wanting the import is in the wrong
    layer — move the module, don't add the import.
    """
    hits = _imports_of("backend", REPO / "knowledge") + _imports_of("ops", REPO / "knowledge")
    assert hits == [], "knowledge/ reaches up into a higher layer:\n  " + "\n  ".join(hits)


def test_backend_never_imports_from_the_operator_layer():
    """backend/ is layer 2 — it may import knowledge/, never ops/."""
    hits = _imports_of("ops", REPO / "backend")
    assert hits == [], "backend/ reaches up into ops/:\n  " + "\n  ".join(hits)


def test_pytest_testpaths_covers_every_test_directory():
    """A package whose tests are not in testpaths is a package CI does not run.

    `pytest backend knowledge` collected 576 of 761 tests once ops/ existed —
    every ops/tests file was skipped, silently and without failing. Adding a
    top-level package means adding its test directory to pytest.ini in the same
    commit.
    """
    cfg = ConfigParser()
    cfg.read(REPO / "pytest.ini")
    configured = set(cfg["pytest"]["testpaths"].split())

    found = {
        d.relative_to(REPO).parts[0]
        for d in REPO.glob("*/tests")
        if d.is_dir() and any(d.glob("test_*.py"))
    }
    missing = sorted(found - configured)
    assert missing == [], (
        f"package(s) with tests missing from pytest.ini testpaths: {missing}. "
        "Their tests are not running."
    )
