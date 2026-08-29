"""Structural invariants — the rules that no unit test would otherwise catch.

These guard the shape of the repository rather than the behaviour of any one
module. Both encode a regression that actually happened, so each failure
message names the fix rather than just the fact.
"""

import re
from configparser import ConfigParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent


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


def test_kriko_core_never_imports_a_domain_layer():
    """kriko/ is the engine — it must know nothing about cars, or about packs.

    This is the load-bearing invariant of goal G6. The whole point of the pivot
    is that adding a product category costs data and no engine code; the moment
    kriko/ imports packs/ or packs/cars/pipeline/, that stops being true and nobody
    notices until a second category is attempted.

    A pack is consumed through the store, never imported. If a core module wants
    something from a pack, the pack should be supplying it as a row.
    """
    hits = sum(
        (
            _imports_of(pkg, REPO / "kriko")
            for pkg in ("backend", "app", "packs", "knowledge")
        ),
        [],
    )
    assert hits == [], (
        "kriko/ reaches into a domain or operator layer:\n  " + "\n  ".join(hits)
    )


def test_packs_never_import_an_interface_or_operator_layer():
    """A pack is data plus a builder. It may sit on kriko/, never above it.

    Packs are the thing third parties author. If a pack can import app/ or
        app.pipeline/, "install a pack" stops meaning "add rows to a database" and starts
    meaning "run someone's code inside the dashboard process".
    """
    hits = _imports_of("app", REPO / "packs") + _imports_of(
        "app.pipeline", REPO / "packs"
    )
    assert hits == [], "packs/ reaches up into a higher layer:\n  " + "\n  ".join(hits)


def test_cars_pipeline_never_imports_an_interface_or_operator_layer():
    """The cars pipeline is pack-owned and may not reach into app/ or ops/.

    Generic engine code is consumed through imports from kriko/, while the
    cars-specific pipeline remains entirely inside its pack.
    """
    hits = _imports_of("app", REPO / "packs" / "cars" / "pipeline") + _imports_of(
        "ops", REPO / "packs" / "cars" / "pipeline"
    )
    assert hits == [], (
        "cars pipeline reaches up into an interface/operator layer:\n  "
        + "\n  ".join(hits)
    )


def test_app_never_imports_the_pipeline_layer():
    """app/ is CLI + web + MCP over kriko/. Pipeline drivers live in app/pipeline/.

    An interface that imports app/pipeline/ drags the extraction stack
    langextract, exa-py) into the serving process, which is exactly what the
    now-deleted Dockerfile COPY-list invariant existed to prevent.
    """
    hits = [
        hit
        for hit in _imports_of("app.pipeline", REPO / "app")
        if not hit.startswith("app/pipeline/")
    ] + _imports_of("backend", REPO / "app")
    assert hits == [], "app/ reaches into the pipeline layer:\n  " + "\n  ".join(hits)


def test_the_legacy_backend_package_stays_deleted():
    """Phase 6 of the pivot removed backend/. This is the ratchet.

    Deleting a package is easy to undo by accident — a stale import, a revert, a
    merge that resurrects a directory. `backend/` held the Postgres ETL, the
    SQLAlchemy models and the 650-line resolver that kriko/lookup replaced;
    every one of those has a successor, so nothing should ever reach for it
    again.
    """
    assert not (REPO / "backend").exists(), (
        "backend/ is back. Its successors: sync/db -> kriko/store, "
        "core/matcher+resolver -> kriko/lookup, api -> app/web, "
        "data/ -> packs/cars/data."
    )
    hits = sum(
        (
            _imports_of("backend", REPO / pkg)
            for pkg in ("kriko", "app", "packs", "knowledge")
        ),
        [],
    )
    assert hits == [], (
        "something still imports the deleted backend/:\n  " + "\n  ".join(hits)
    )


def test_pytest_testpaths_covers_every_test_directory():
    """A package whose tests are not in testpaths is a package CI does not run.

    `pytest backend knowledge` collected 576 of 761 tests once a pipeline package existed —
        every pipeline test file was skipped, silently and without failing. Adding a
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


# ── every shipped pack must actually build ───────────────────────────────


def test_every_pack_in_the_repo_builds_and_is_not_empty(tmp_path):
    """A pack that cannot be built is a pack nobody can install.

    This exists because `packs/cars` spent a commit in exactly that state:
    Phase 6a moved `trust/source_tiers.yaml` in from the deleted `backend/`
    unchanged, the builder expected a different shape, and nothing noticed —
    the parity and lookup suites all run against fixtures they build
    themselves, so the one pack that actually ships was the one pack never
    built in CI.

    The emptiness check is the second half, and it is not belt-and-braces. A
    pack may ship its own builder (`packs/<name>/build.py`) when its data
    needs generating rather than transcribing; pointing the generic builder at
    such a pack succeeds and produces a pack with nothing in it. "It built" is
    therefore not the property worth asserting — "it answers" is.

    Per the generalization principle this is the mechanism, not a fix for
    cars: a third-party pack added tomorrow is covered with nothing to
    register.
    """
    import importlib
    from pathlib import Path

    from kriko.pack import build
    from kriko.store.db import connect

    roots = sorted(p.parent for p in Path("packs").glob("*/pack.toml"))
    assert roots, "no packs found — the glob is wrong, not the repo"

    for root in roots:
        out_path = tmp_path / f"{root.name}.kpack"
        own_builder = (root / "build.py").exists()
        if own_builder:
            module = importlib.import_module(f"packs.{root.name}.build")
            out = module.build(out_path)
            out = out[0] if isinstance(out, tuple) else out
        else:
            out = build.build(root, out_path)

        assert out.exists(), f"{root} produced no pack file"
        conn = connect(out)
        subjects = conn.execute("SELECT COUNT(*) AS n FROM subjects").fetchone()["n"]
        claims = conn.execute("SELECT COUNT(*) AS n FROM claims").fetchone()["n"]
        conn.close()
        assert subjects and claims, (
            f"{root} built empty ({subjects} subjects, {claims} claims)"
            + (
                " — its own build.py ran"
                if own_builder
                else " — it has no build.py, so the generic builder ran"
            )
        )
