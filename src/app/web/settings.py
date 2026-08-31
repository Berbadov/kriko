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


@dataclass(frozen=True)
class Settings:
    store_path: Path = DEFAULT_STORE
    packs_dir: Path = Path("packs")
    title: str = "Kriko"
    analysis_log_path: Path = Path("logs/analyses.jsonl")
    #: UI state — history and interface settings. Beside the engine's store in
    #: ~/.kriko, never inside it: see app/web/state.py for why.
    app_state_path: Path = DEFAULT_STORE.parent / "app.sqlite"

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
        }
        base.update(overrides)
        return cls(**base)
