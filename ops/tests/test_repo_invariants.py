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


def test_kriko_core_never_imports_a_domain_layer():
    """kriko/ is the engine — it must know nothing about cars, or about packs.

    This is the load-bearing invariant of goal G6. The whole point of the pivot
    is that adding a product category costs data and no engine code; the moment
    kriko/ imports packs/ or backend/, that stops being true and nobody notices
    until a second category is attempted.

    A pack is consumed through the store, never imported. If a core module wants
    something from a pack, the pack should be supplying it as a row.
    """
    hits = sum(
        (_imports_of(pkg, REPO / "kriko")
         for pkg in ("backend", "ops", "packs", "apps")),
        [],
    )
    assert hits == [], (
        "kriko/ reaches into a domain or operator layer:\n  " + "\n  ".join(hits)
    )


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


# ── Serving image completeness ───────────────────────────────────────────────
#
# deploy/Dockerfile copies a hand-listed slice of knowledge/ rather than the
# whole package, deliberately: it keeps mistralai/langextract/exa-py off the
# serving image. The cost of that choice is that moving or adding a module the
# serving path imports produces an image which builds clean and dies at request
# time — the test suite cannot see it, because tests run against the full source
# tree where every module is present.
#
# This computes what the image actually needs (the transitive closure of
# knowledge/ imports reachable from backend/) and checks the Dockerfile copies
# it. Static, so it costs milliseconds instead of a container build.

_KNOWLEDGE_IMPORT = re.compile(r"^\s*(?:from|import)\s+(knowledge(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")


def _knowledge_imports(path: Path) -> set[str]:
    return {
        m.group(1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if (m := _KNOWLEDGE_IMPORT.match(line))
    }


def _resolve(dotted: str) -> set[Path]:
    """Dotted module -> its .py file plus every package __init__.py above it."""
    parts = dotted.split(".")
    files = set()
    for i in range(1, len(parts) + 1):
        base = REPO.joinpath(*parts[:i])
        if base.is_dir():
            files.add(base / "__init__.py")
        elif base.with_suffix(".py").exists():
            files.add(base.with_suffix(".py"))
    return {f for f in files if f.exists()}


def test_dockerfile_copies_every_knowledge_module_the_serving_path_imports():
    seed: set[str] = set()
    for path in REPO.glob("backend/**/*.py"):
        if "/tests/" in path.as_posix():
            continue
        seed |= _knowledge_imports(path)

    required: set[Path] = set()
    queue = list(seed)
    while queue:
        for found in _resolve(queue.pop()):
            if found in required:
                continue
            required.add(found)
            queue.extend(_knowledge_imports(found))

    dockerfile = (REPO / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    copied = {
        m.group(1)
        for m in re.finditer(r"^COPY\s+(\S+)", dockerfile, re.M)
    }

    def is_copied(rel: str) -> bool:
        # Either the file itself, or a directory COPY that contains it.
        return rel in copied or any(
            c.endswith("/") and rel.startswith(c) for c in copied
        )

    missing = sorted(
        rel for f in required
        if not is_copied(rel := f.relative_to(REPO).as_posix())
    )
    assert missing == [], (
        "deploy/Dockerfile does not COPY module(s) the serving path imports:\n  "
        + "\n  ".join(missing)
        + "\n\nThe image will build successfully and fail at request time. Add a "
          "COPY line for each, keeping the stdlib-only rule in mind — if the "
          "module pulls in an LLM dependency it does not belong on this image."
    )
