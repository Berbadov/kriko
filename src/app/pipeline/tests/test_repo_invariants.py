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
        str(d.parent.relative_to(REPO))
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


UI_SRC = REPO / "ui" / "src"

# Pack vocabulary. The engine's domain-freedom is checked by
# src/kriko/tests/test_core_is_domain_free.py walking kriko/'s AST; the same
# failure mode is now reachable in TypeScript, where no Python test looks. One
# `if (key === "make")` in a form component and G6 is over at the DOM boundary.
PACK_VOCABULARY = (
    "make",
    "model",
    "engine_code",
    "gearbox",
    "fuel",
    "mileage",
    "vehicle",
    "car",
)


def test_ui_contains_no_pack_vocabulary():
    """ui/ builds its forms from pack rows, never from a hardcoded key list.

    Identity keys come from /api/identity-keys/{pack_id} and context keys from
    /api/packs/{pack_id}/vocabulary. A literal key name in the frontend is the
    same scalability bug as a Python constant, in a language the AST test does
    not read.

    Test fixtures are excluded: they need realistic-looking values, and a
    fixture cannot leak into what a user sees.
    """
    if not UI_SRC.is_dir():
        return
    pattern = re.compile(rf"\b(?:{'|'.join(PACK_VOCABULARY)})\b", re.IGNORECASE)
    hits = []
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix not in {".ts", ".svelte"} or path.name.endswith(".test.ts"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert not hits, (
        "pack vocabulary in ui/src — build the field from the pack's own rows "
        "(/api/identity-keys, /api/packs/{id}/vocabulary) instead:\n" + "\n".join(hits)
    )


def test_no_hand_written_frontend_survives():
    """app.js was replaced by ui/, not supplemented by it.

    Two frontends in one directory is how the built bundle silently stops
    being what the server serves.
    """
    stale = [
        p.name
        for p in (REPO / "src" / "app" / "web" / "static").glob("*")
        if p.name in {"app.js", "app.css"}
    ]
    assert not stale, (
        f"{stale} still in the served static dir — the Svelte build in ui/ "
        f"replaces them; delete them and rebuild."
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

    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text()
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
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("//")[0]
            assert not forbidden.search(code), (
                f"{path.relative_to(REPO)}:{number} puts engine vocabulary in "
                f"the shell: {line.strip()!r}. Rust owns the sidecar's "
                f"lifetime and nothing else — see tauri/README.md."
            )


def test_the_boot_screen_can_render_a_failure():
    """A sidecar that dies must produce an explanation, not a blank page.

    The boot page is plain HTML with no build step for the same reason: it has
    to render when everything else is broken.
    """
    page = (TAURI / "shell-ui" / "index.html").read_text()
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
    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text()
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

    worker = (REPO / "extension" / "background.js").read_text()
    found = re.search(r"DEFAULT_API_BASE\s*=\s*.http://127\.0\.0\.1:(\d+)", worker)
    assert found, "extension/background.js no longer declares DEFAULT_API_BASE"
    assert int(found.group(1)) == EXTENSION_PORT, (
        f"the extension talks to port {found.group(1)} and the server binds "
        f"{EXTENSION_PORT}. Nothing would report the mismatch."
    )
    sidecar = (REPO / "src" / "app" / "sidecar.py").read_text()
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
    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text()
    sidecar = (REPO / "src" / "app" / "sidecar.py").read_text()
    assert flag in main_rs, f"the shell does not pass {flag} — an orphan survives a crash"
    assert flag in sidecar, f"the sidecar does not accept {flag} — it would fail to start"


def test_a_sidecar_that_cannot_start_still_gets_a_window():
    """`Err` from `start_engine` has nowhere to be read.

    The window is created hidden and shown once the engine is healthy, so an
    error returned to the boot page renders into something invisible: the app
    "does not open", with no window and no message. Every failure path has to
    reach `emit_failure`, which shows the window itself.
    """
    main_rs = (TAURI / "src-tauri" / "src" / "main.rs").read_text()
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
    config = json.loads((TAURI / "src-tauri" / "tauri.conf.json").read_text())
    hooks = config["bundle"]["windows"]["nsis"]["installerHooks"]
    script = TAURI / "src-tauri" / hooks
    assert script.exists(), f"{hooks} is configured but missing"
    text = script.read_text()

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

    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
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
            undeclared.append(str(path.relative_to(REPO)))

    assert undeclared == [], (
        "these files live under src/ but no package-data rule ships them, so a "
        "wheel install cannot read them:\n  "
        + "\n  ".join(undeclared)
        + "\nAdd them to [tool.setuptools.package-data] in pyproject.toml (and "
        "to packaging/kriko-sidecar.spec's `datas` if the sidecar needs them)."
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
            lines = path.read_text().splitlines()
            tree = ast.parse("\n".join(lines))
            sorted_args = {
                id(node.args[0])
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("sorted", "min", "max", "len", "any", "all")
                and node.args
            }
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
                        f"{path.relative_to(REPO)}:{node.lineno}: {line.strip()}"
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
    pyproject = (REPO / "pyproject.toml").read_text().lower()
    for driver in ("psycopg", "asyncpg", "sqlalchemy", "alembic"):
        assert driver not in pyproject, (
            f"{driver} is a dependency again — the store is SQLite, and the "
            f"engine talks to it with the stdlib sqlite3 module"
        )


def test_the_app_wears_the_extension_palette():
    """The app's default theme tracks the extension's live stylesheet.

    This exists because it already went wrong: the `lemonade` theme was ported
    from `extension/colors_and_type.css`, a file nothing loads — the extension
    has no HTML outside its test fixtures, and `manifest.json` ships
    `hover_lite/hover_lite.css` into a shadow root instead. The port was
    faithful to a stylesheet that had not painted a pixel in months, and the
    only thing that caught it was the reader looking at both windows.

    So the check is not "panel.css is correct" — that is a fact about one
    afternoon. It is "panel.css and the live sheet still agree", which fails
    the moment somebody restyles the extension and forgets the app, in either
    direction.
    """
    live = (REPO / "extension" / "hover_lite" / "hover_lite.css").read_text()
    theme = (REPO / "ui" / "src" / "styles" / "themes" / "panel.css").read_text()

    def declared(css: str, prop: str) -> str | None:
        found = re.search(rf"^\s*{re.escape(prop)}:\s*([^;]+);", css, re.M)
        return found.group(1).strip().lower() if found else None

    # Ground and accent are the two values a glance actually registers; if
    # these drift the two windows stop looking like one product, whatever the
    # other forty tokens say.
    for label, live_prop, theme_prop in (
        ("the ground", "--bg-base", "--n-0"),
        ("the accent", "--accent", "--accent"),
    ):
        want, got = declared(live, live_prop), declared(theme, theme_prop)
        assert want is not None, f"{live_prop} is gone from hover_lite.css"
        assert got == want, (
            f"{label} drifted: the extension paints {live_prop}: {want}, the "
            f"app's panel theme has {theme_prop}: {got}. Whichever moved "
            f"first, the other has to follow — they are one product."
        )

    for family in ("ibm plex sans", "ibm plex mono"):
        assert family in theme.lower(), (
            f"panel.css no longer names {family}, which hover_lite.css uses"
        )

    # And the app must actually open in it. A theme nobody selects is a
    # preference, not an identity.
    assert 'DEFAULT_THEME: Theme = "panel"' in (
        REPO / "ui" / "src" / "lib" / "theme.ts"
    ).read_text(), "the app no longer opens wearing the extension's palette"
