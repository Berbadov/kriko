"""What the operator sets, all by environment, none required to try it out."""

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
    #: Seals page addresses at rest. Set it on a real server: without it a key is
    #: made and kept beside the database, which protects nothing from whoever
    #: copies the disk.
    secret: str = field(default_factory=lambda: os.environ.get("KRIKO_CLOUD_SECRET", ""))
    #: Where alerts are pushed. An ntfy server, the public one or your own.
    ntfy_base: str = field(default_factory=lambda: os.environ.get("KRIKO_CLOUD_NTFY", "https://ntfy.sh"))
    sweep_minutes: int = field(default_factory=lambda: _int("KRIKO_CLOUD_SWEEP_MINUTES", 30))
    max_groups: int = field(default_factory=lambda: _int("KRIKO_CLOUD_MAX_GROUPS", 2000))
    max_watches_per_group: int = field(default_factory=lambda: _int("KRIKO_CLOUD_MAX_WATCHES", 50))
    max_pages: int = field(default_factory=lambda: _int("KRIKO_CLOUD_MAX_PAGES", 20000))
    max_blob_bytes: int = field(default_factory=lambda: _int("KRIKO_CLOUD_MAX_BLOB", 262144))
    #: Groups created per address per hour. A phone and a computer make one.
    registrations_per_hour: int = field(default_factory=lambda: _int("KRIKO_CLOUD_REGISTRATIONS", 10))
    #: A group nobody has touched for this long is deleted, with its watches.
    forget_after_days: int = field(default_factory=lambda: _int("KRIKO_CLOUD_FORGET_DAYS", 180))
