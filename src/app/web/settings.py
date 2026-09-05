"""Configuration as a value, not as module-level globals.

The old hub kept `REPO_ROOT`, `DATA_DIR`, `EXPORT_DIR` and `LEDGER_PATH` as
module constants computed at import time. That is what made its endpoints
untestable and blocked backlog B28's router split: you could not point the app
at a temporary store without monkeypatching the module, and two tests could not
run against two stores at once.

Passing a `Settings` through the app factory fixes both, and is why the routers
below can be tested without a real ~/.kriko.
"""

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


@dataclass(frozen=True)
class Settings:
    store_path: Path = DEFAULT_STORE
    packs_dir: Path = Path("packs")
    title: str = "Kriko"
    analysis_log_path: Path = Path("logs/analyses.jsonl")
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

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        import os

        base = {
            "store_path": Path(os.environ.get("KRIKO_STORE", DEFAULT_STORE)),
            "packs_dir": Path(os.environ.get("KRIKO_PACKS", "packs")),
            "analysis_log_path": Path(
                os.environ.get("KRIKO_ANALYSES_LOG", "logs/analyses.jsonl")
            ),
            "app_state_path": Path(
                os.environ.get("KRIKO_APP_STATE", DEFAULT_STORE.parent / "app.sqlite")
            ),
            "pack_index_url": os.environ.get(
                "KRIKO_PACK_INDEX", cls.pack_index_url
            ),
            "releases_url": os.environ.get("KRIKO_RELEASES_URL", cls.releases_url),
            "extension_port_bound": os.environ.get("KRIKO_EXTENSION_BOUND") == "1",
        }
        base.update(overrides)
        return cls(**base)
