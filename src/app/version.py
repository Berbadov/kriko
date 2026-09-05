"""What this install is running — three answers, not one.

The binary and the knowledge update on different clocks (see `kriko/pack/
updates.py`), and the store's schema on a third. A reader who says "I'm on
0.2.6" may mean any of them, so the health endpoint names all three and lets
the asker pick.

`app_version` reads the installed distribution's metadata rather than a
constant, because a constant here would be a fifth place the number lives:
`test_every_version_string_in_the_tree_agrees` already pins pyproject,
Cargo.toml, package.json and tauri.conf.json to one value, and reading the
metadata inherits that guarantee instead of adding to the list. In a frozen
sidecar the metadata may be absent, which is a packaging gap, not a crash — so
the fallback is `"unknown"` and the endpoint still answers.
"""

import sqlite3
from pathlib import Path

UNKNOWN = "unknown"


def app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("kriko")
    except PackageNotFoundError:
        return UNKNOWN


def installed_versions(store_path: Path) -> list[dict]:
    """Every installed pack and the version of it that is live.

    Fails open: a store that does not exist yet (first run, before any pack is
    installed) is an empty list, not an error — the health endpoint is the one
    thing that must answer while everything else is still missing.
    """
    if not Path(store_path).exists():
        return []
    try:
        with sqlite3.connect(f"file:{store_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT pack_id, version FROM packs ORDER BY pack_id"
            ).fetchall()
    except sqlite3.Error:
        return []
    return [{"pack_id": r["pack_id"], "version": r["version"]} for r in rows]
