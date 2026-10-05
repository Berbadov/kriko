"""Structural invariants — the rules that no unit test would otherwise catch.

These guard the shape of the repository rather than the behaviour of any one
module. Both encode a regression that actually happened, so each failure
message names the fix rather than just the fact.
"""

import ast
import json
import re
import subprocess
from configparser import ConfigParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent.parent.parent
SRC = REPO / "src"

# The layering guards below only check what they can see. A wrong REPO/SRC
# root doesn't raise — `_imports_of` just rglobs an empty or nonexistent
# directory and returns no hits, so a broken path computation makes every
# guard below pass while scanning nothing. This is exactly the regression a
# src/ move introduced once already (the scans still pointed at REPO/"kriko"
# and REPO/"app" after those packages moved under src/) — caught only by
# manually injecting a cross-layer import and noticing nothing complained.
# Fail loudly here, at collection time, naming the path, instead of relying
# on that kind of manual check again.
for _root in (SRC / "kriko", SRC / "app", REPO / "packs"):
    assert _root.is_dir() and any(_root.rglob("*.py")), (
        f"{_root} holds no Python files — the layering guards below would "
        f"scan nothing and pass. Fix this path, not the tests."
    )


# A cross-package import at the start of a line, with or without indentation:
# both `from backend.x import y` and `import backend.x as z`, top-level or
# deferred inside a function body.
def _rel(path: Path) -> str:
    """A repo-relative path, in the one separator this file compares against.

    Every literal here is written with `/`, and on Windows `relative_to`
    hands back the other one. Two of these gates compared the two dialects
    and so could only ever pass on a POSIX host: the pipeline-layer check
    excused `src/app/pipeline/` and matched nothing, and the testpaths
    check asked whether `src\app` was among `src/app` and said no. Both
    then reported a violation the tree did not have, on the only machine
    that runs the gate at all.
    """
    return path.relative_to(REPO).as_posix()


def _imports_of(package: str, tree: Path) -> list[str]:
    pattern = re.compile(rf"^\s*(?:from|import)\s+{package}\b")
    hits = []
    for path in sorted(tree.rglob("*.py")):
        if "/tests/" in path.as_posix() or "__pycache__" in path.as_posix():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.match(line):
                hits.append(f"{_rel(path)}:{n}: {line.strip()}")
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
            _imports_of(pkg, SRC / "kriko")
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
    (langextract, exa-py) into the serving process, which is exactly what the
    now-deleted Dockerfile COPY-list invariant existed to prevent.
    """
    hits = [
        hit
        for hit in _imports_of("app.pipeline", SRC / "app")
        if not hit.startswith("src/app/pipeline/")
    ] + _imports_of("backend", SRC / "app")
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
            _imports_of("backend", root)
            # "knowledge" is a pre-backend/ historical name (see
            # docs/historical/); it never exists on disk today, and
            # _imports_of degrades to no hits on a missing directory — kept
            # here deliberately so the ratchet still names it rather than
            # silently forgetting it existed.
            for root in (SRC / "kriko", SRC / "app", REPO / "packs", REPO / "knowledge")
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
        _rel(d.parent)
        for d in list(REPO.glob("*/tests")) + list(REPO.glob("src/*/tests"))
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


# ── the desktop shell ─────────────────────────────────────────────────────
# tauri/ is optional: no Rust toolchain is needed for the wheel or this suite.
# But three things about it are load-bearing and break invisibly — a blank
# window, or an engine reimplemented in Rust — so they are pinned in Python
# where CI already runs.

TAURI = REPO / "tauri"


def test_the_shell_and_the_sidecar_agree_on_the_handshake():
    """One string decides whether the app opens or shows a white rectangle.

    Rust reads the sidecar's first line of stdout to learn the port. If either
    side renames the marker, the window never opens and nothing anywhere says
    why — there is no shared type to break and no test the compiler runs.
    """
    from app.sidecar import PORT_LINE

    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    declared = re.search(r'const PORT_LINE: &str = "([^"]+)"', main_rs)
    assert declared, "main.rs no longer declares PORT_LINE"
    assert declared.group(1) == PORT_LINE, (
        f"the shell greps for {declared.group(1)!r} but app/sidecar.py prints "
        f"{PORT_LINE!r}. The window would never open."
    )


def test_the_shell_holds_no_engine_logic():
    """Tauri wraps the Python engine; it does not become a second one.

    The moment a query, a rank or a pack read exists in Rust, there are two
    engines to keep in agreement and the layering fan in CLAUDE.md is a
    drawing rather than a rule. The shell's whole job is the sidecar's
    lifetime.
    """
    rust = list((TAURI / "src-tauri" / "src").rglob("*.rs"))
    assert rust, "no Rust sources found — fix this path, not the test"

    # Engine vocabulary, not shell vocabulary. `spawn`, `kill`, `health` and
    # `port` are exactly what a supervisor is allowed to know about.
    forbidden = re.compile(
        r"\b(sqlite|rusqlite|SELECT\s|INSERT\s|claim|pack_id|subject_id|"
        r"relevance|severity)\b",
        re.IGNORECASE,
    )
    for path in rust:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("//")[0]
            assert not forbidden.search(code), (
                f"{_rel(path)}:{number} puts engine vocabulary in "
                f"the shell: {line.strip()!r}. Rust owns the sidecar's "
                f"lifetime and nothing else — see tauri/README.md."
            )


def test_the_boot_screen_can_render_a_failure():
    """A sidecar that dies must produce an explanation, not a blank page.

    The boot page is plain HTML with no build step for the same reason: it has
    to render when everything else is broken.
    """
    page = (TAURI / "shell-ui" / "index.html").read_text(encoding="utf-8")
    assert "kriko://failed" in page, "the boot screen ignores the failure event"
    # The stderr goes through textContent. It is a subprocess's output, so an
    # innerHTML assignment carrying it would be an injection with a very short
    # path from "the engine crashed" to "the engine crashed and ran something".
    assert "textContent" in page
    injectable = [
        line
        for line in page.splitlines()
        if "innerHTML" in line.split("//")[0] and 'innerHTML = ""' not in line
    ]
    assert injectable == [], f"stderr must not reach innerHTML: {injectable}"
    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert "kriko://failed" in main_rs, "the shell never emits a failure"
    assert "kill_engine" in main_rs, (
        "nothing kills the sidecar — an orphaned uvicorn holds the store's WAL "
        "lock and breaks the next launch"
    )


def test_the_extension_and_the_server_agree_on_a_port():
    """The extension's only address, pinned on both sides.

    A page cannot be told a random port: no filesystem, no channel from the
    shell. So the number is hardcoded in `extension/background.js` and bound by
    the sidecar, and nothing but this test connects the two — a drift here is an
    extension that silently does nothing, with no error anywhere.
    """
    from app.web.settings import EXTENSION_PORT

    worker = (REPO / "extension" / "background.js").read_text(encoding="utf-8")
    found = re.search(r"DEFAULT_API_BASE\s*=\s*.http://127\.0\.0\.1:(\d+)", worker)
    assert found, "extension/background.js no longer declares DEFAULT_API_BASE"
    assert int(found.group(1)) == EXTENSION_PORT, (
        f"the extension talks to port {found.group(1)} and the server binds "
        f"{EXTENSION_PORT}. Nothing would report the mismatch."
    )
    sidecar = (REPO / "src" / "app" / "sidecar.py").read_text(encoding="utf-8")
    assert "EXTENSION_PORT" in sidecar, (
        "the sidecar no longer binds the extension's fixed port — the desktop "
        "app would only be on an OS-chosen one, which the extension cannot know"
    )


def test_the_shell_tells_the_sidecar_to_die_with_it():
    """The flag is the only thing covering a *crashed* shell.

    `kill_engine` runs on window close and on exit. Neither runs when the shell
    is killed or panics, and the survivor keeps the store's WAL lock — and, on
    Windows, its own image, which is what made an installer fail with "Error
    opening file for writing: kriko-sidecar.exe". A flag spelled on one side
    only is silent: argparse would reject it and the window would never open.
    """
    flag = "--exit-with-parent"
    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    sidecar = (REPO / "src" / "app" / "sidecar.py").read_text(encoding="utf-8")
    assert flag in main_rs, f"the shell does not pass {flag} — an orphan survives a crash"
    assert flag in sidecar, f"the sidecar does not accept {flag} — it would fail to start"


def test_a_sidecar_that_cannot_start_still_gets_a_window():
    """`Err` from `start_engine` has nowhere to be read.

    The window is created hidden and shown once the engine is healthy, so an
    error returned to the boot page renders into something invisible: the app
    "does not open", with no window and no message. Every failure path has to
    reach `emit_failure`, which shows the window itself.
    """
    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    body = main_rs.split("fn start_engine")[1].split("\nfn ")[0]
    assert "emit_failure" in body, (
        "start_engine can fail without showing the window — the process would "
        "have no window at all, which is the blank-window bug in its worst form"
    )


def test_the_windows_installer_stops_a_running_engine_first():
    """The install failure a reader actually hit, pinned.

    NSIS overwrites the sidecar in place. A live one — leaked by an earlier
    version, or by a crash — keeps its onefile image mapped, and the installer
    stops with Abort/Retry/Ignore, all three of which are wrong. So the
    installer kills it, and the name it kills has to be the name Tauri ships.
    """
    config = json.loads((TAURI / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    hooks = config["bundle"]["windows"]["nsis"]["installerHooks"]
    script = TAURI / "src-tauri" / hooks
    assert script.exists(), f"{hooks} is configured but missing"
    text = script.read_text(encoding="utf-8")

    binaries = config["bundle"]["externalBin"]
    name = Path(binaries[0]).name
    assert f"{name}.exe" in text, (
        f"the hook does not stop {name}.exe, which is the file the installer "
        f"fails to open for writing"
    )
    for macro in ("NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL"):
        assert macro in text, f"{hooks} defines no {macro}"
    # /T because the pid holding the image is a child of the one we spawned.
    assert "/T" in text, "taskkill without /T leaves the onefile child alive"


def test_every_data_file_under_src_is_declared_as_package_data():
    """A file read from disk must be shipped, or only editable installs work.

    `src/kriko/store/schema.sql` is read at every `connect()`. It was declared
    nowhere, so an editable install worked, a real wheel raised
    `FileNotFoundError` on the first query, and the PyInstaller build failed the
    same way — one missing line, three broken distributions, none of them
    visible from the source tree.

    So the rule is mechanical rather than remembered: every non-Python file
    under `src/` is either declared in `pyproject.toml`'s `package-data` or
    named here as deliberately unshipped.
    """
    import tomllib

    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["tool"]["setuptools"]["package-data"]

    # Build the set of (package, glob) rules as concrete path prefixes.
    globs: list[tuple[Path, str]] = []
    for package, patterns in declared.items():
        base = SRC / Path(package.replace(".", "/"))
        for pattern in patterns:
            globs.append((base, pattern))

    # Not distributed, on purpose: build metadata and caches.
    ignored_parts = {"__pycache__", ".egg-info", ".pytest_cache"}

    undeclared = []
    for path in SRC.rglob("*"):
        if not path.is_file() or path.suffix == ".py":
            continue
        if any(part in ignored_parts or part.endswith(".egg-info") for part in path.parts):
            continue
        if not any(
            path in set(base.glob(pattern)) for base, pattern in globs
        ):
            undeclared.append(_rel(path))

    assert undeclared == [], (
        "these files live under src/ but no package-data rule ships them, so a "
        "wheel install cannot read them:\n  "
        + "\n  ".join(undeclared)
        + "\nAdd them to [tool.setuptools.package-data] in pyproject.toml (and "
        "to packaging/kriko-sidecar.spec's `datas` if the sidecar needs them)."
    )


def test_the_frozen_spec_bundles_every_data_file_it_reads_from_disk():
    """`app/models.toml` was declared in pyproject.toml but not in the spec.

    The previous test only reads pyproject.toml's package-data, which is what a
    wheel install uses — it has no view of packaging/kriko-sidecar.spec's own
    `datas` list, which is what the frozen PyInstaller build actually ships.
    `app/models.toml` was in the former and missing from the latter, so every
    editable install and every wheel install had a model catalogue and every
    frozen desktop build did not: `install_default()` raised FileNotFoundError
    on first startup and every screen that prices a run showed "cost unknown".

    So this one reads the spec file itself (as text — it is not import-safe
    off Windows, since it does `import winpty` under `sys.platform == "win32"`)
    and checks that a fixed set of paths this codebase is known to read from
    disk at runtime — the ones the spec's own comment documents — each appear
    somewhere in its `datas` list.
    """
    spec_text = (REPO / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")
    datas_start = spec_text.index("datas=[")
    datas_end = spec_text.index("]", datas_start)
    datas_block = spec_text[datas_start:datas_end]

    # Each of these must appear as a distinctive fragment inside `datas=[...]` —
    # either the EXTENSION variable the spec builds from ROOT, or the
    # literal filename for a path built inline (as models.toml's fix does).
    required = {
        "schema.sql": "the store's DDL",
        "models.toml": "the shipped model catalogue",
        "EXTENSION": "the browser extension",
    }
    missing = [
        f"{fragment} ({why})"
        for fragment, why in required.items()
        if fragment not in datas_block
    ]
    assert missing == [], (
        "packaging/kriko-sidecar.spec's `datas` list is missing files this "
        "codebase reads from disk at runtime, so the frozen sidecar would "
        "start with them absent:\n  " + "\n  ".join(missing)
    )


def test_the_catalog_is_never_scanned_in_directory_order():
    """`Path.glob` returns directory order, which is a property of the disk.

    A part fitted to two models has two candidate answers, and whichever the
    filesystem hands back first becomes the search query the pipeline runs.
    That is a machine-dependent pipeline: `_find_make_model_for_part("k9k")`
    resolved to `clio_5` locally and `megane_4` on a CI runner, from identical
    data. Sorting costs nothing here — no scan is hot — and it converts "it
    depends" into a property of the catalog.

    Opt out on the line itself with `# any-order:` and a reason, for a scan
    whose result genuinely cannot depend on order (a membership test, a count).
    """
    scans = ("glob", "rglob", "iterdir")
    offenders = []
    for root in (SRC, REPO / "packs"):
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            tree = ast.parse("\n".join(lines))
            # A scan is excused when the order it returns cannot reach the
            # result. Two shapes do that, and this only used to see the first:
            #
            #   sorted(p.glob("*"))                    the scan IS the argument
            #   sorted(f(p) for p in root.glob("*"))   the scan feeds it
            #
            # The second is the one people actually write, and it was being
            # reported as a violation while already sorted — so the honest fix
            # for it looked like adding `# any-order:` to a line that did not
            # need it, which is how an opt-out marker stops meaning anything.
            # A set or dict comprehension is the third shape: order cannot
            # survive into a set, so `{p.stem for p in root.glob("*")}` is
            # order-free by construction rather than by assertion.
            order_free = ("sorted", "min", "max", "len", "any", "all",
                          "set", "frozenset", "sum")
            sorted_args = set()
            for node in ast.walk(tree):
                subtrees = []
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in order_free
                    and node.args
                ):
                    subtrees.append(node.args[0])
                elif isinstance(node, (ast.SetComp, ast.DictComp)):
                    subtrees.extend(gen.iter for gen in node.generators)
                for subtree in subtrees:
                    for inner in ast.walk(subtree):
                        sorted_args.add(id(inner))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in scans
                    and id(node) not in sorted_args
                ):
                    line = lines[node.lineno - 1]
                    if "any-order:" in line:
                        continue
                    offenders.append(
                        f"{_rel(path)}:{node.lineno}: {line.strip()}"
                    )
    assert offenders == [], (
        "these scans depend on directory order — wrap them in sorted(), or "
        "mark the line `# any-order: <why>` if the result cannot depend on it:\n"
        + "\n".join(offenders)
    )


def test_every_tracked_path_is_checkoutable_on_windows_and_macos():
    """A filename this machine accepts is not a filename every machine accepts.

    Six 541-byte `imgui.ini` files, written into the repo root by an unrelated
    GUI program with non-UTF-8 names, were swept in by a `git add -A`. Linux
    stored them happily; the macOS runner said `unable to create file: Illegal
    byte sequence` and the Windows runner said `invalid path` — both failing in
    *checkout*, before a single line of ours ran. The desktop build looked
    broken on two of three platforms for a reason that had nothing to do with
    the desktop build.

    The rules are Windows', because they are the strictest: printable ASCII
    only, none of `<>:"|?*`, and no trailing dot or space in any component.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")

    forbidden = set('<>:"|?*')
    offenders = []
    for raw in filter(None, tracked):
        if any(byte < 0x20 or byte > 0x7E for byte in raw):
            offenders.append(f"{raw!r}: not printable ASCII")
            continue
        name = raw.decode()
        for part in name.split("/"):
            if set(part) & forbidden:
                offenders.append(f"{name}: illegal character on Windows")
            elif part != part.rstrip(". "):
                offenders.append(f"{name}: component ends in a dot or space")

    assert offenders == [], (
        "these tracked paths cannot be checked out on Windows or macOS:\n"
        + "\n".join(offenders)
    )


def test_the_app_stays_standalone():
    """No container, no database server, no deployment.

    Kriko was a Postgres-and-compose deployment before the pivot, and the
    difference is not stylistic: a user installs a desktop app, they do not
    stand up a stack. The two SQLite files exist so that there is nothing to
    run. Docker's residue is also actively harmful here — a stale compose
    service with a bind mount into the checkout recreates directories inside
    the repo as root, which is how `backend/` came back after being deleted.

    Docs may *describe* the retired stack; this checks that the machinery
    cannot return.
    """
    names = ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml")
    tracked = (
        subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        )
        .stdout.splitlines()
    )
    found = [
        path
        for path in tracked
        if Path(path).name in names or path.startswith("deploy/")
    ]
    assert found == [], f"the deployment stack is back: {found}"

    # A Postgres driver in the dependencies means something intends to talk to
    # a server, whatever the docs say.
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8").lower()
    for driver in ("psycopg", "asyncpg", "sqlalchemy", "alembic"):
        assert driver not in pyproject, (
            f"{driver} is a dependency again — the store is SQLite, and the "
            f"engine talks to it with the stdlib sqlite3 module"
        )


def test_no_two_tracked_files_differ_only_in_case():
    """A repo that only checks out on Linux.

    `NextStep.test.ts` and `nextStep.test.ts` sat beside each other for weeks —
    two real test files, one for the component and one for the function it
    reads. On this machine that is fine. On the machine this project is
    actually shipping to it is not: Windows and macOS default to
    case-insensitive filesystems, so a clone collapses the pair into whichever
    one git wrote last and the other test silently stops existing. Not fails —
    stops existing, which no suite reports.

    The convention the repo already uses is the fix (`report.test.ts` for the
    module, `Report.svelte.test.ts` for the component), so this test is only
    here to keep the next collision from surviving a review.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")

    seen: dict[str, str] = {}
    clashes: list[str] = []
    for path in filter(None, tracked):
        key = path.lower()
        if key in seen and seen[key] != path:
            clashes.append(f"{seen[key]} vs {path}")
        seen.setdefault(key, path)

    assert clashes == [], (
        "these paths differ only in case, so a Windows or macOS clone keeps "
        f"one of each pair and loses the other: {clashes}"
    )


# --- Workflows that run on more than one OS -------------------------------
#
# A step's default shell is the runner's, not the author's: bash on Linux and
# macOS, **PowerShell on Windows**. So a POSIX-ism in a `run:` block is not a
# style question, it is a step that passes on two thirds of the matrix. The
# case that produced this test: `cargo metadata --locked > /dev/null` — in
# PowerShell that redirect names the path `C:\dev\null`, whose parent does not
# exist, and the step fails before running anything. Two runners green, one
# red, on a line that has nothing to do with either.
#
# The repo already had the convention (five steps in `desktop.yml` declare
# `shell: bash`); what it did not have was anything that noticed a sixth
# skipping it.

#: Redirect targets and devices that only exist under a POSIX shell. Kept
#: narrow on purpose: `&&`, `$(...)` and friends work in PowerShell 7 or fail
#: loudly on the author's own machine, while these fail *only* on Windows and
#: only in CI.
POSIX_ONLY = ("/dev/null", "/dev/stdout", "/dev/stderr", "2>&1 |")

WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))


def _multi_os_jobs(text: str) -> bool:
    """Does this workflow put a step on a Windows runner at all?

    Read off the text rather than a YAML parse of the matrix, because the
    runner can be named in a matrix entry, an `include`, or a bare `runs-on` —
    and the question here only has to be answered conservatively. A false
    positive costs one `shell: bash`.
    """
    return "windows" in text


def test_there_are_workflows_to_check():
    """A glob that matches nothing passes every check under it.

    Was `>= 2` until 2026-09-13, when `ci.yml` was deleted: this account has no
    Actions minutes, so every run since the workflow was un-paused failed within
    seconds without ever being allocated a runner, and its jobs moved into
    `tools/gate.sh`. `desktop.yml` remains, and it is the one the Windows-shell
    check below was written for. The floor stays above zero rather than going
    with the workflow, because the failure this guards is a glob that silently
    matches nothing.
    """
    assert len(WORKFLOWS) >= 1, [p.name for p in WORKFLOWS]


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_posix_only_step_runs_unshelled_on_a_windows_runner(workflow: Path):
    text = workflow.read_text(encoding="utf-8")
    if not _multi_os_jobs(text):
        pytest.skip(f"{workflow.name} names no Windows runner")

    lines = text.splitlines()
    offenders = []
    for index, line in enumerate(lines):
        if line.strip().startswith("#"):
            continue
        if not any(token in line for token in POSIX_ONLY):
            continue
        # A step is `- name:`/`- run:` and everything indented under it until
        # the next sibling `- `. Walk back to that boundary and look for a
        # shell declaration anywhere inside it.
        start = index
        while start > 0 and not lines[start].lstrip().startswith("- "):
            start -= 1
        end = index
        while end + 1 < len(lines) and not lines[end + 1].lstrip().startswith("- "):
            end += 1
        step = "\n".join(lines[start : end + 1])
        if re.search(r"^\s*shell:\s*(bash|sh)\s*$", step, re.MULTILINE):
            continue
        offenders.append(f"{workflow.name}:{index + 1}: {line.strip()}")

    assert offenders == [], (
        "these steps use a POSIX-only redirect and do not declare "
        "`shell: bash`, so they run under PowerShell on the Windows runner and "
        f"fail there and only there: {offenders}"
    )


#: A run of comment, in either JavaScript form. Stripped before the scan below
#: because prose is allowed to name anything: this gate is about what the code
#: *matches on*, and a comment explaining a Turkish heading is exactly how the
#: rule stays legible to the next reader.
_JS_COMMENTS = (
    re.compile(r"/\*.*?\*/", re.DOTALL),
    re.compile(r"//[^\n]*"),
)

#: A lone non-ASCII character between delimiters: `/ı/`, `"ş"`, `'İ'`. That is
#: a character fold — the closed-vocabulary exception CLAUDE.md carves out for
#: fixed engineering categories — and both `foldTerm`s need one. A *word* is
#: not a fold, and that is the distinction this gate draws.
_LONE_CHARACTER = re.compile(r"""([/"'])([^\x00-\x7F])\1""")


def test_the_extension_speaks_no_sites_own_language():
    """extension/ matches on terms the pack declared, never on its own.

    Before this gate the panel held four Turkish damage headings, five
    Turkish-to-English equipment buckets and eleven alert rules with their
    thresholds and their English advice. Every one of them was a manual edit
    someone had to remember for a new listing site, a new market, or a
    category that is not cars — the same failure mode `_MAKE_MAP` and
    `SIBLING_CODE_FAMILIES` had, in the one language none of the AST gates in
    this file can read.

    They now live in the adapter's `local_panel` block and reach the browser
    over `/api/adapters`. A non-ASCII word back in this directory means
    someone put a site's own vocabulary back into the client, where a pack
    author cannot reach it.

    Punctuation is not vocabulary: an em dash in a sentence the panel prints
    is English typography. Only letters count.
    """
    ext = REPO / "extension"
    if not ext.is_dir():
        pytest.skip("no extension/ in this tree")
    offenders = []
    scanned = 0
    for path in sorted(ext.rglob("*.js")):
        if "tests" in path.parts or "node_modules" in path.parts:
            continue
        scanned += 1
        source = path.read_text(encoding="utf-8")
        for pattern in _JS_COMMENTS:
            source = pattern.sub(lambda m: "\n" * m.group(0).count("\n"), source)
        source = _LONE_CHARACTER.sub("", source)
        for n, line in enumerate(source.splitlines(), 1):
            words = [c for c in line if ord(c) > 127 and c.isalpha()]
            if words:
                offenders.append(f"{_rel(path)}:{n}: {''.join(words)}")
    # A gate that found no files to read is a gate that has stopped working.
    assert scanned >= 4, f"only {scanned} script(s) scanned — is the rglob right?"
    assert not offenders, (
        "a site's own vocabulary is back in extension/ — declare it in the "
        "adapter's `local_panel` block and match it through the interpreter "
        "instead:\n" + "\n".join(offenders)
    )


def test_the_shipped_panel_declares_what_the_interpreter_reads():
    """Every rule key the interpreter reads is one a pack actually ships.

    The two halves drift in opposite directions and both are silent. A key the
    interpreter stopped reading leaves an alert that never fires; a key it
    reads that nothing ships leaves a branch nothing exercises. Neither shows
    up as a failure anywhere else.

    The honoured set is read off the source rather than listed here, because a
    list here would be the very thing this file exists to ban — a hand-kept
    enumeration that goes stale the first time someone adds a rule form and
    forgets to come back. `rule.<name>` is how the interpreter reads a key,
    and there is exactly one interpreter.

    What this cannot see is a branch that is present but dead — `if (false)`
    around a key still named on the next line reads as honoured here. That is
    a behaviour question and `extension/tests/local_panel.test.js` is where it
    is caught; a source gate that claimed otherwise would be lying.
    """
    adapter = REPO / "packs" / "cars" / "adapters" / "sahibinden.json"
    panel = json.loads(adapter.read_text(encoding="utf-8")).get("local_panel")
    assert panel, "the cars adapter ships no local_panel block"

    source = (REPO / "extension" / "hover_lite" / "hover_lite.js").read_text(
        encoding="utf-8"
    )
    honoured = set(re.findall(r"\brule\.(\w+)", source))
    shipped = {key for rule in panel["alerts"] for key in rule if not key.startswith("_")}
    assert honoured, "no rule keys found in the panel — has the interpreter moved?"
    assert shipped - honoured == set(), (
        f"the shipped rules use keys the interpreter never reads, so they do "
        f"nothing: {sorted(shipped - honoured)}"
    )
    assert honoured - shipped == set(), (
        f"the interpreter reads keys nothing ships, so no test exercises "
        f"them: {sorted(honoured - shipped)}"
    )


def _text_calls_without_encoding(tree: ast.AST) -> list[tuple[int, str]]:
    """Every text-mode file call in `tree` that never names an encoding."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name not in {"read_text", "write_text", "open"}:
            continue
        if any(kw.arg == "encoding" for kw in node.keywords):
            continue
        if name == "open":
            # `open` is the one name here that other objects also answer to,
            # and the first version of this gate reported three calls nobody
            # could act on: `os.open`, which returns a file descriptor and has
            # no encoding to pass, and two `provenance.open(researcher)` -- a
            # method that happens to share the word. A gate whose findings are
            # mostly noise gets its whole output skimmed, so it has to be able
            # to tell a file open from a homonym.
            #
            # The tell is the mode: a real one is `open(path, "a")` or
            # `path.open("a")` or no argument at all. A call whose first
            # argument is some other expression is somebody else's `open`.
            builtin = isinstance(func, ast.Name)
            if not builtin and isinstance(func.value, ast.Name) and func.value.id == "os":
                continue
            args = node.args[1:] if builtin else node.args
            mode = None
            if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                mode = args[0].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if not builtin and mode is None and (node.args or node.keywords):
                continue
            # Binary mode has no encoding to name, and `read_bytes`/`write_bytes`
            # never reach here at all. Only a text-mode open is a finding -- but
            # a mode we cannot read statically stays one, because the default
            # is text.
            if mode and "b" in mode:
                continue
        found.append((node.lineno, name))
    return found


def test_no_text_file_is_read_or_written_in_the_platform_encoding():
    """`read_text`/`write_text`/`open` must always name their encoding.

    Without `encoding=`, Python uses `locale.getencoding()` — UTF-8 on the CI
    images and on macOS, **cp1252 on a Turkish or Western-European Windows
    install**. Every byte this project stores is UTF-8: pack YAML, adapters,
    briefs, fixtures, the Turkish site vocabulary in `local_panel`. So the
    same call that passes everywhere else raises `UnicodeDecodeError` on the
    one machine the app is actually built and shipped from.

    That is not hypothetical. Sixty-six tests failed on the Windows host with
    `'charmap' codec can't decode byte 0x9d`, and clearing them took two
    hundred and ten call sites. Those edits were the patch; this is the
    mechanism, because the next unencoded call would have been written the
    same week and nothing would have said so until a reader's install fell
    over.

    The rule is a rule, not a preference: pass `encoding="utf-8"` explicitly,
    or use `read_bytes`/`write_bytes` when the payload is not text. Bytes are
    also how you avoid the other half of this, which no source gate can see —
    `write_text` translates a newline to CRLF on Windows, and a file written
    that way reads as a whole-file diff to everyone else.
    """
    # Files git tracks, not every `.py` under the root. An exclusion list is
    # the wrong shape for this: it named `.venv` and this host also has a
    # `.venv-win`, so the gate spent its time reading pytest's and
    # PyInstaller's vendored source and failed on *their* unencoded `open()`
    # calls -- findings nobody in this repo can act on, in files nobody here
    # wrote. Every name such a list could learn is another name it can miss,
    # and "what this project is answerable for" is already recorded exactly
    # once, by git.
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.py"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout.decode().split("\0")

    offenders = []
    for name in sorted(filter(None, tracked)):
        path = REPO / name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # Not this guard's business to report: the suite could not import
            # the file either way, and whatever does report it will say so
            # more clearly than an encoding gate would.
            continue
        for lineno, name in _text_calls_without_encoding(tree):
            offenders.append(f"{_rel(path)}:{lineno}  {name}()")

    assert not offenders, (
        "these calls use the platform's default encoding, which is cp1252 on "
        "the Windows host this app ships from, while every file they touch is "
        'UTF-8. Pass encoding="utf-8", or read_bytes/write_bytes if the '
        "payload is not text:\n  " + "\n  ".join(offenders)
    )


def test_every_new_backlog_item_says_when_it_is_done():
    """docs/DOCTRINE.md §1: a request is written down with what counts as done.

    Three requests of 2026-09 (the research limiters) never reached the
    backlog and drifted into chips, a dropdown and nothing. From B141 on, an
    item without a **Done when:** line is not an item yet. Earlier ones are
    history and are left as they are.
    """
    import re

    text = (REPO / "backlog.md").read_text(encoding="utf-8", errors="replace")
    heads = list(re.finditer(r"^### B(\d+)\b.*$", text, re.M))
    missing = []
    for at, head in enumerate(heads):
        if int(head.group(1)) < 141:
            continue
        end = heads[at + 1].start() if at + 1 < len(heads) else len(text)
        body = text[head.end():end].split("\n## ", 1)[0]
        if "**Done when:**" not in body:
            missing.append(head.group(0).strip())
    assert not missing, (
        "backlog items with no **Done when:** line — write what the reader will "
        "be able to see, per docs/DOCTRINE.md §1:\n  " + "\n  ".join(missing))
