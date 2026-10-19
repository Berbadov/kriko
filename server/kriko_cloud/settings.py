"""What the operator sets, all by environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("KRIKO_CLOUD_DB", "kriko-cloud.sqlite")))
    #: Seals watched addresses at rest. Without it a key is made and kept beside the
    #: database, which protects nothing from whoever copies the disk.
    secret: str = field(default_factory=lambda: os.environ.get("KRIKO_CLOUD_SECRET", ""))
    #: The word that lets the first device claim this relay. Until the relay is
    #: claimed anyone who can reach it could do so, so a relay with no setup word
    #: refuses every claim.
    setup: str = field(default_factory=lambda: os.environ.get("KRIKO_CLOUD_SETUP", ""))
    #: Where alerts are pushed. An ntfy server, the public one or your own.
    ntfy_base: str = field(default_factory=lambda: os.environ.get("KRIKO_CLOUD_NTFY", "https://ntfy.sh"))
    sweep_minutes: int = field(default_factory=lambda: _int("KRIKO_CLOUD_SWEEP_MINUTES", 30))
    max_watches: int = field(default_factory=lambda: _int("KRIKO_CLOUD_MAX_WATCHES", 100))
    max_blob_bytes: int = field(default_factory=lambda: _int("KRIKO_CLOUD_MAX_BLOB", 262144))
