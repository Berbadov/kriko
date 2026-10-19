"""What this install is running — three answers, not one.

The binary and the knowledge update on different clocks (see `kriko/pack/
updates.py`), and the store's schema on a third. A reader who says "I'm on
0.2.6" may mean any of them, so the health endpoint names all three and lets
the asker pick.

`app_version` reads the installed distribution's metadata rather than a
constant, because a constant here would be a fifth place the number lives:
`test_every_version_string_in_the_tree_agrees` already pins pyproject,
the Cargo manifest, package.json and the MSI to one value, and reading the
metadata inherits that guarantee instead of adding to the list. In a frozen
sidecar the metadata may be absent, which is a packaging gap, not a crash — so
the fallback is `"unknown"` and the endpoint still answers.
"""

import functools
import sqlite3
from pathlib import Path

UNKNOWN = "unknown"


@functools.cache
def app_version() -> str:
    """The installed distribution's version, read once per process.

    Cached because `/api/health` is polled (at startup, and by the extension) and
    `importlib.metadata.version` scans every distribution on `sys.path` each time:
    about 1.8 ms per call measured, most of a health answer. The version a process
    reports is the one it was started with, which is the claim the endpoint makes.
    """
    from importlib.metadata import distributions

    # The newest of every copy found, not the first: an update lays the new
    # engine folder over the old one, and the old `kriko-<n>.dist-info` stays
    # beside the new one. `importlib.metadata.version` answers with whichever
    # comes first on the path, which made 0.2.4 report itself as 0.2.3 and offer
    # itself as an update to itself.
    found = {d.version for d in distributions(name="kriko") if d.version}
    if not found:
        return UNKNOWN
    return max(found, key=_order)


def _order(number: str) -> tuple[int, ...]:
    """A version as numbers, so "0.10.0" sorts after "0.2.3".

    Only the leading dotted digits count; a release suffix sorts as its base.
    That is enough to tell this app's own releases apart, and it keeps the
    packaging library out of the frozen engine.
    """
    parts: list[int] = []
    for piece in number.split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
        if len(digits) != len(piece):
            break
    return tuple(parts)


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
