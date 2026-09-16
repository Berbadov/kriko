"""Configuration as a value, not as module-level globals.

The old hub kept `REPO_ROOT`, `DATA_DIR`, `EXPORT_DIR` and `LEDGER_PATH` as
module constants computed at import time. That is what made its endpoints
untestable and blocked backlog B28's router split: you could not point the app
at a temporary store without monkeypatching the module, and two tests could not
run against two stores at once.

Passing a `Settings` through the app factory fixes both, and is why the routers
below can be tested without a real ~/.kriko.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from kriko.store.db import DEFAULT_STORE

#: The one port anything outside this process is allowed to assume.
#:
#: The desktop sidecar takes an OS-chosen port on purpose — a port it has
#: already bound cannot be stolen between the choosing and the binding — but a
#: Chrome extension has no way to be told a random number: it cannot read a
#: port file, and there is no channel from the shell to a page. So the sidecar
#: *also* listens here when it can, and this constant is the single place the
#: number lives. `extension/background.js` hardcodes the same one, which
#: test_the_extension_and_the_server_agree_on_a_port keeps honest.
EXTENSION_PORT = 8787

#: Everything this process is allowed to write, under one root.
#:
#: `~/.kriko` already holds both SQLite files, so it is not a new concept —
#: but until 0.3.2 the *other* writable paths were relative (`packs`,
#: `logs/analyses.jsonl`, `dist/`), which resolves against the current working
#: directory. From a checkout that is the repo and it looks correct. From an
#: installed app the working directory is wherever the shell was launched
#: from — on Windows, `C:\Program Files\Kriko`, which is read-only. Every
#: analysis tried to append to a log it could not create, and every pack build
#: tried to write a `.kpack` into Program Files. Both surfaced as a 500 with
#: no hint that a path was involved.
#:
#: The rule that replaces it: **no default path in `Settings` is relative.**
#: `test_writable_paths.py` enforces it, because the next path added here
#: would otherwise be written the same way.
KRIKO_HOME = DEFAULT_STORE.parent


def source_root() -> Path | None:
    """The checkout this module was imported from, or None in a frozen build.

    A developer running from a clone means `packs/` and `logs/` in the repo —
    that is where their data already is, and moving it under `~/.kriko` on an
    upgrade would silently orphan it. So the source tree wins *when there is
    one*. `sys.frozen` is what tells us there is not: PyInstaller unpacks this
    module into a temporary directory, whose parents are meaningless.
    """
    if getattr(sys, "frozen", False):
        return None
    root = Path(__file__).resolve().parents[3]
    return root if (root / "packs").is_dir() else None


def default_packs_dir() -> Path:
    root = source_root()
    return root / "packs" if root else KRIKO_HOME / "packs"


def default_analysis_log() -> Path:
    root = source_root()
    return (root or KRIKO_HOME) / "logs" / "analyses.jsonl"


def default_dist_dir() -> Path:
    root = source_root()
    return (root or KRIKO_HOME) / "dist"


@dataclass(frozen=True)
class Settings:
    store_path: Path = DEFAULT_STORE
    packs_dir: Path = default_packs_dir()
    title: str = "Kriko"
    analysis_log_path: Path = default_analysis_log()
    #: Where `pack build` leaves the `.kpack` it made when the caller names no
    #: output. A build is the app's own artifact, not the reader's document, so
    #: it lands beside the store rather than in whatever directory the desktop
    #: shell happened to inherit.
    dist_dir: Path = default_dist_dir()
    #: UI state — history and interface settings. Beside the engine's store in
    #: ~/.kriko, never inside it: see app/web/state.py for why.
    app_state_path: Path = DEFAULT_STORE.parent / "app.sqlite"
    #: Where to look for newer packs. A `packs.json` published beside the
    #: installers on the releases page — knowledge ships on its own clock, so
    #: `latest` rather than a pinned tag, and overridable for anyone running
    #: their own catalogue.
    pack_index_url: str = (
        "https://github.com/Berbadov/kriko/releases/latest/download/packs.json"
    )
    #: Where a reader goes to fetch a build by hand. The app updates itself
    #: through Tauri's signed updater when a release carries signatures; until
    #: one does, this page is the only way to move between versions, and About
    #: says so rather than implying an in-app switch that does not exist.
    #: Overridable so a fork does not send its readers here.
    releases_url: str = "https://github.com/Berbadov/kriko/releases"
    #: Did this process get `EXTENSION_PORT`? Only the sidecar knows — it tries
    #: the bind and carries on without it, because failing to start over a
    #: convenience socket would be worse than losing the socket. But the
    #: extension has no other address, so when the bind lost, every listing the
    #: reader opens will fail with a connection error and look exactly like a
    #: botched install. The extension page says so instead of letting them
    #: reinstall it twice.
    extension_port_bound: bool = False
    #: Is a desktop shell supervising this process?
    #:
    #: Not a guess and not a probe — the shell *says so*, by passing
    #: `--supervised` when it spawns us. Nothing else can know it: a headless
    #: `python -m app.sidecar` and a Tauri-supervised one are identical over
    #: HTTP, they answer the same endpoints on the same ports, and the only
    #: difference is whether anybody is reading our stdout.
    #:
    #: Which is exactly the difference that matters to the browser extension.
    #: "Open in Kriko" prints a line for the shell to act on; with no shell
    #: attached that line goes nowhere, and the reader sees a browser tab open
    #: for reasons the extension could not explain because it did not know.
    #: `/api/focus` answers `delivery: "no_shell"` instead of claiming a
    #: window was raised, and a tab is then the *right* answer rather than a
    #: silent fallback.
    shell_attached: bool = False

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        import os

        base = {
            "store_path": Path(os.environ.get("KRIKO_STORE", DEFAULT_STORE)),
            "packs_dir": Path(
                os.environ.get("KRIKO_PACKS", default_packs_dir())
            ),
            "analysis_log_path": Path(
                os.environ.get("KRIKO_ANALYSES_LOG", default_analysis_log())
            ),
            "dist_dir": Path(os.environ.get("KRIKO_DIST", default_dist_dir())),
            "app_state_path": Path(
                os.environ.get("KRIKO_APP_STATE", DEFAULT_STORE.parent / "app.sqlite")
            ),
            "pack_index_url": os.environ.get(
                "KRIKO_PACK_INDEX", cls.pack_index_url
            ),
            "releases_url": os.environ.get("KRIKO_RELEASES_URL", cls.releases_url),
            "extension_port_bound": os.environ.get("KRIKO_EXTENSION_BOUND") == "1",
            "shell_attached": os.environ.get("KRIKO_SUPERVISED") == "1",
        }
        base.update(overrides)
        return cls(**base)  # type: ignore[arg-type]
