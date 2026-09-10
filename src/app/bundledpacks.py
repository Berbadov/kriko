"""The knowledge an installer carries, and how it reaches the store.

A fresh install opened onto an empty store. Nothing was wrong with it — every
screen worked, `/api/health` was green — and there was nothing to look up,
because the only ways a pack had ever reached a store were a file the reader
found themselves and an update index that answers 404 while this repository is
private (B63). So the app shipped a knowledge engine with no knowledge and the
reader had to go get some.

It also meant a *fix to a pack* could not be delivered at all. The queries the
reader watched find nothing were `Volkswagen Golf 1.5_TSI 150 hp common
problems`, and closing that needed a new alias tier in the pack's own rows
(B101) — so the engine's half shipped and their installed 0.1.1 kept producing
the old searches. A defect fixed in a pack that no release can hand over is not
fixed.

So the installer carries the first-party packs as data, the same way it already
carries the browser extension, and startup installs what is missing or newer.
Three rules, and they are the whole design:

1. **Missing gets installed.** A first run ends with knowledge in it.
2. **Newer gets installed, older never does.** The comparison is the pack's
   declared version, and a store holding something *newer* than the bundle is
   left alone — a reader who installed 0.2.0 by hand must not be walked
   backwards by an app upgrade.
3. **A failure here is never why the app will not start.** Bundled knowledge is
   a convenience over a working store, not a precondition for one, so
   everything below reports and continues.

Nothing here fetches. This module reads files that are already on the disk the
installer wrote, which is why it is allowed to run inside startup at all.
"""

import logging
import os
import sqlite3
from pathlib import Path

from kriko.pack import updates
from kriko.store import packstore
from kriko.store.db import connect

log = logging.getLogger(__name__)

__all__ = ["source_dir", "bundled", "seed"]

#: Where PyInstaller unpacks them, beside the code. Mirrors
#: `app/extension_src` rather than inventing a second convention.
_PACKAGED = "packs_bundled"


def source_dir() -> Path | None:
    """Where the bundled packs are on *this* installation, or None.

    Deliberately narrower than `extension.source_dir`, which falls back to the
    checkout: this is knowledge that gets *written into a store*, and the two
    reasons not to do that from a checkout are both real. A developer's `dist/`
    holds whatever they last built — the first run of this module found a
    `drill.kpack` frozen before `gate_terms` existed in the schema — and the
    28 tests that start a lifespan would each have a 2 MB cars pack installed
    into their temporary store by the act of starting the app.

    So: what the installer unpacked, or what `KRIKO_BUNDLED_PACKS` names.
    The environment variable is the developer's and the test's door, and it is
    explicit because seeding a store is not a thing to do by accident.

    None rather than an exception — a bundle built without packs is a
    packaging shape, not a fault, and this runs inside startup.
    """
    named = os.environ.get("KRIKO_BUNDLED_PACKS", "").strip()
    if named:
        candidate = Path(named).expanduser()
        return candidate if candidate.is_dir() else None
    packaged = Path(__file__).resolve().parent / _PACKAGED
    return packaged if packaged.is_dir() else None


def _identify(path: Path) -> tuple[str, str] | None:
    """One artifact's `(pack_id, version)`, read out of the artifact.

    A `.kpack` *is* a SQLite database — that is how `packstore.install` reads
    one — so its identity comes from its own `packs` row rather than from its
    file name. Trusting the name is how a renamed file installs as something it
    is not, and a build that produced `cars.kpack` from a different directory
    would be believed.

    Opened read-only through a URI so a corrupt or truncated file cannot be
    written to by the act of looking at it.
    """
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = conn.execute("SELECT pack_id, version FROM packs LIMIT 2").fetchall()
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()
    # Exactly one, the same rule `packstore.install` enforces — checked here so
    # a multi-pack file is skipped with a name in the log rather than raising
    # inside startup.
    return (str(row[0][0]), str(row[0][1])) if len(row) == 1 else None


def bundled(root: Path | None = None) -> list[tuple[Path, str, str]]:
    """Each carried artifact as `(path, pack_id, version)`, sorted by path.

    `root` overrides where to look. It exists so a test can hand over a
    directory of real artifacts rather than monkeypatching `source_dir` — the
    thing most worth testing here is what happens to a *store*, and a test that
    replaced the lookup would be testing its own stub.
    """
    root = root if root is not None else source_dir()
    if root is None:
        return []
    out = []
    for path in sorted(root.glob("*.kpack")):
        identified = _identify(path)
        if identified is None:
            log.warning("bundled pack %s is unreadable, skipping", path.name)
            continue
        out.append((path, *identified))
    return out


def _newer(candidate: str, installed: str) -> bool:
    """Is `candidate` a later version than `installed`?

    Borrowed from `kriko.pack.updates` rather than written again. Version
    ordering is the engine's to define, and the update path already had to
    decide it — two comparators are two places to disagree about whether 0.10.0
    beats 0.9.0. An uncomparable version answers False: leaving a store alone is
    always safe, and the reader can still install the file by hand.
    """
    if not (updates.comparable(candidate) and updates.comparable(installed)):
        return False
    return updates._parts(candidate) > updates._parts(installed)


def seed(store_path, source: Path | None = None) -> list[dict]:
    """Install every bundled pack the store is missing or behind on.

    Returns one row per artifact considered, each with `pack_id`, `version` and
    `action` — `installed`, `upgraded`, `current`, `store_is_newer` or
    `failed`. The list is what makes this testable and what the log prints; a
    silent seeder is one nobody can debug from a reader's screenshot.
    """
    carried = bundled(source)
    if not carried:
        return []

    rows: list[dict] = []
    # Closed by hand rather than with `with`, which on a sqlite3 connection is
    # a transaction and not a handle: an unclosed store is a held WAL lock, and
    # on Windows a held lock at startup is the class of bug the tray and the
    # NSIS hook exist to prevent.
    conn = connect(Path(store_path))
    try:
        have = {
            row["pack_id"]: row["version"]
            for row in packstore.installed_packs(conn)
        }
        for path, pack_id, version in carried:
            installed = have.get(pack_id)
            if installed is None:
                action = "installed"
            elif _newer(version, installed):
                action = "upgraded"
            elif version == installed:
                rows.append({"pack_id": pack_id, "version": version,
                             "action": "current"})
                continue
            else:
                # Deliberately not touched. An app upgrade that walked a
                # hand-installed newer pack backwards would be destroying the
                # reader's own work to deliver ours.
                rows.append({"pack_id": pack_id, "version": installed,
                             "action": "store_is_newer"})
                continue
            try:
                packstore.install(conn, path)
            except Exception as exc:
                log.warning("could not install bundled pack %s: %s", pack_id, exc)
                rows.append({"pack_id": pack_id, "version": version,
                             "action": "failed", "why": str(exc)})
                continue
            rows.append({"pack_id": pack_id, "version": version, "action": action})
            log.info("%s bundled pack %s %s", action, pack_id, version)
        conn.commit()
    finally:
        conn.close()
    return rows
