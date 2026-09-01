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
# `datas` — the built frontend lives in src/app/web/static/ and is loaded from
# the filesystem, not imported. Without it the app serves 404 for its own UI.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
STATIC = ROOT / "src" / "app" / "web" / "static"

if not (STATIC / "index.html").exists():
    raise SystemExit(
        "src/app/web/static/index.html is missing — run "
        "`npm --prefix ui run build` before freezing, or the app ships with no UI"
    )

a = Analysis(
    [str(ROOT / "src" / "app" / "sidecar.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(STATIC), "app/web/static")],
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
    ],
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
