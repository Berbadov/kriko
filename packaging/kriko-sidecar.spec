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
# `datas` — two things in this repo are read from disk rather than imported, and
# both are invisible to PyInstaller's import graph: the built frontend
# (src/app/web/static/, or the app 404s on its own UI) and the store's DDL
# (src/kriko/store/schema.sql, or every query raises FileNotFoundError). The
# second one was found by running this build, not by reading the code — see
# test_every_data_file_under_src_is_declared_as_package_data, which now fails
# if a third one appears.

import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)
from freeze_imports import mcp_submodules

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

a = Analysis(
    [str(ROOT / "src" / "app" / "sidecar.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(STATIC), "app/web/static"),
        (str(ROOT / "src" / "kriko" / "store" / "schema.sql"), "kriko/store"),
        (str(EXTENSION), "app/extension_src"),
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
    + mcp_submodules(),
    hookspath=[],
    runtime_hooks=[],
    # The research API plane and the whole pipeline are optional extras; a
    # reader installing packs must not carry mistralai or yt-dlp.
    excludes=["tkinter", "matplotlib", "mistralai", "yt_dlp", "textual", "langextract"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Tauri's externalBin wants `<name>-<target-triple>`; the CI job renames the
# artifact rather than hardcoding a triple here, so this spec stays the same
# file on all three runners.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="kriko-sidecar" + (".exe" if sys.platform == "win32" else ""),
    debug=False,
    strip=False,
    upx=False,
    # console=True, deliberately, even though this is a GUI app's child.
    # PyInstaller's windowed mode leaves `sys.stdout` as None on Windows, and
    # the first thing this binary does is print its port — the handshake would
    # raise before the server ever started. The terminal window is suppressed
    # on the spawning side instead: Tauri's shell plugin creates the child with
    # CREATE_NO_WINDOW, so nothing flashes.
    console=True,
)
