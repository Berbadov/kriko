# PyInstaller spec for the sidecar the desktop shell spawns.
#
#     pyinstaller packaging/kriko-sidecar.spec
#
# One file, one binary, no Python on the reader's machine. Built per OS on a CI
# runner of that OS — PyInstaller does not cross-compile, which is why the
# bundle job in .github/workflows/desktop.yml is a three-OS matrix rather than
# one clever Linux job.
#
# Two things here are not defaults and both cost a day to rediscover:
#
# `hiddenimports` — uvicorn and FastAPI find their protocol and lifespan
# implementations by string, so PyInstaller's import graph cannot see them. The
# frozen binary starts and then fails at the first request with
# `ModuleNotFoundError: uvicorn.protocols.http.h11_impl`.
#
# `mcp_submodules()` — the same problem one layer out. `--mcp` runs the MCP
# stdio server out of this binary, and FastMCP resolves transports and
# validators by string at startup. The failure is a binary that answers HTTP
# perfectly and dies on the agent's first `initialize`. It lives in
# packaging/freeze_imports.py because a spec file cannot be tested and this one
# has already been wrong once — collecting all of `mcp` pulls in `mcp.cli`,
# which raises "typer is required" and fails the freeze on every runner.
#
# `datas` — five things in this repo are read from disk rather than imported,
# and every one is invisible to PyInstaller's import graph: the built frontend
# (src/app/web/static/, or the app 404s on its own UI), the store's DDL
# (src/kriko/store/schema.sql, or every query raises FileNotFoundError), the
# browser extension, the first-party packs, and the shipped model catalogue
# (src/app/models.toml, or install_default() throws FileNotFoundError on every
# frozen startup and every screen that prices a run shows "cost unknown"). The
# DDL was found by running this build, not by reading the code; models.toml
# was the same story one release later — see
# test_every_data_file_under_src_is_declared_as_package_data, which now fails
# if another one appears under src/, and
# test_the_frozen_spec_bundles_every_data_file_it_reads_from_disk, which reads
# this file's own `datas` list and fails if it drops behind that set.
#
# `winpty-agent.exe` — the same class of gap, one layer further: not source
# and not read by `import`, it is spawned by `winpty.dll` via `CreateProcess`
# at a path relative to itself. PyInstaller's binary walker (`pefile`) reads
# `_winpty.cp314-win_amd64.pyd`'s import table and correctly follows *that*
# to `winpty.dll` and `conpty.dll` with no help from this file — but a
# `CreateProcess` target is not a DLL import, so the walker has no path to
# it and 0.7.4 shipped without it. The terminal opened, connected, and never
# printed a shell prompt: `SESSION.start()` raised inside the websocket
# handler the instant `winpty.dll` looked for the agent beside itself and
# found nothing, closing the socket before a single byte reached the reader
# — a black rectangle with a blinking cursor, no error visible anywhere in
# the UI. Found by running the frozen exe through
# `pyi-archive_viewer -l`, which lists `winpty\\winpty.dll` and
# `winpty\\conpty.dll` but not `winpty\\winpty-agent.exe`; not caught by any
# test, because none of them run the frozen binary's PTY on Windows.

import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from freeze_imports import CONSOLE_MODULES, FROZEN_EXCLUDES, kriko_submodules, mcp_submodules

ROOT = Path(SPECPATH).parent
STATIC = ROOT / "src" / "app" / "web" / "static"

# The browser extension travels *inside* the sidecar, unpacked to
# `app/extension_src` where `app/extension.py` looks for it. It is data, not
# code: nothing imports it, so PyInstaller cannot see it, and an installer that
# omitted it would leave the extension page offering a folder that is not
# there. Only what a browser loads goes in — `extension/tests/` and the dead
# `colors_and_type.css` are excluded by app.extension.SHIPPED, which this
# mirrors by copying the directory and letting the staging step filter.
EXTENSION = ROOT / "extension"

# The first-party knowledge travels inside the sidecar too, unpacked to
# `app/packs_bundled` where `app/bundledpacks.py` looks for it, and startup
# installs whatever the store is missing or behind on. Until 0.7.1 the
# installer carried none, so a fresh install opened onto an empty store — and,
# worse, a defect whose fix lives in a pack's rows could not be delivered by
# any release at all: B101's new alias tier shipped its engine half while the
# reader's installed cars 0.1.1 kept producing the searches that found nothing.
# Every file is listed rather than globbed because PyInstaller's `datas` takes
# paths, not patterns.
PACKS = sorted((ROOT / "dist").glob("*.kpack"))

if not PACKS:
    raise SystemExit(
        "dist/ carries no .kpack — the app ships its first-party knowledge and "
        "an install with none opens onto an empty store. Build them first:\n"
        "  python -m app.cli build packs/cars  --out dist/cars.kpack\n"
        "  python -m app.cli build packs/drill --out dist/drill.kpack"
    )

if not (EXTENSION / "manifest.json").exists():
    raise SystemExit(
        "extension/manifest.json is missing — the app ships the browser "
        "extension and cannot install one it does not carry"
    )

if not (STATIC / "index.html").exists():
    raise SystemExit(
        "src/app/web/static/index.html is missing — run "
        "`npm --prefix ui run build` before freezing, or the app ships with no UI"
    )

# See the `winpty-agent.exe` note above `datas` for why this is a `binaries`
# entry rather than something PyInstaller finds on its own. Only Windows
# installs `pywinpty` at all (pyproject.toml's `sys_platform == 'win32'`
# marker), so this is empty and inert on the other two runners in the
# desktop.yml matrix.
WINPTY_BINARIES: list[tuple[str, str]] = []
if sys.platform == "win32":
    import winpty

    winpty_dir = Path(winpty.__file__).parent
    agent = winpty_dir / "winpty-agent.exe"
    if not agent.exists():
        raise SystemExit(
            f"{agent} is missing from the installed pywinpty — the terminal "
            "would freeze without a way to spawn its shell. Reinstall "
            "pywinpty and check its version still ships this file."
        )
    WINPTY_BINARIES = [(str(agent), "winpty")]

a = Analysis(
    [str(ROOT / "src" / "app" / "sidecar.py")],
    pathex=[str(ROOT / "src")],
    binaries=WINPTY_BINARIES,
    datas=[
        (str(STATIC), "app/web/static"),
        (str(ROOT / "src" / "kriko" / "store" / "schema.sql"), "kriko/store"),
        (str(ROOT / "src" / "app" / "models.toml"), "app"),
        # Versioned benchmark corpora are read beside their modules. Discover
        # all app JSON resources so a new suite cannot disappear when frozen.
        *((str(resource), "app") for resource in sorted((ROOT / "src" / "app").glob("*.json"))),
        (str(EXTENSION), "app/extension_src"),
        *((str(pack), "app/packs_bundled") for pack in PACKS),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "app.web.app",
        "app.web.tasks",
        "app.findings",
        "kriko.research.agent",
        "kriko.research.api",
        "app.mcp_server",
    ]
    + list(CONSOLE_MODULES)
    + mcp_submodules()
    + kriko_submodules(),
    hookspath=[],
    runtime_hooks=[str(ROOT / "packaging" / "restore_stdio.py")],
    # See FROZEN_EXCLUDES for why each is here.
    excludes=list(FROZEN_EXCLUDES),
    noarchive=False,
)
pyz = PYZ(a.pure)

# The name carries no target triple: `kriko-gpui` looks for exactly
# `kriko-sidecar` beside its own executable, so this spec stays the same file
# on every runner.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="kriko-sidecar" + (".exe" if sys.platform == "win32" else ""),
    debug=False,
    strip=False,
    upx=False,
    # A GUI-subsystem binary cannot allocate a flashing console when a CLI
    # starts --mcp. The runtime hook restores inherited pipes for both the
    # engine's port handshake and MCP's bidirectional stdio protocol.
    console=sys.platform != "win32",
)
