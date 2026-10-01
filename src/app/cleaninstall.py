"""A clean install, rebuilt by the new flow (B188, decision D4).

The reader's sentence: "Remove every package so you can rebuild them." The
catch, and the reason this is a module rather than a loop over the Packs
screen's own delete buttons: cars and drill come back at the next start,
because `app/bundledpacks.py` seeds any bundled pack the store is missing.
A reset that quietly restores half of what it removed is worse than no
reset.

So one confirmed action does three things, and the third is the one that
makes the first two mean anything:

1. every installed pack is uninstalled, through `packstore.uninstall`, the
   same path as the per-pack button, so every dependent row goes with it;
2. every draft is discarded, because `~/.kriko/drafts/<slug>/` blocks a new
   draft of the same name ("drafts/x already holds a pack.toml");
3. a `packs_reset` row is written to `app.sqlite`, and `bundledpacks.seed`
   refuses to run while it is there. History and settings are kept, per D4:
   history rows refer to packs by id, and a lookup of a removed pack says
   so rather than pretending it never existed.
"""

import shutil
import sqlite3
from pathlib import Path

from kriko.store import packstore
from kriko.store.db import connect

#: The settings key that says "this reader emptied the store on purpose".
#: Seeding checks it, so the guard and the marker are one name.
RESET_KEY = "packs_reset"


def reset(store_path, app_state_path) -> dict:
    """Remove every pack and draft. History and settings are kept.

    Returns one row per pack removed and the drafts discarded, because a
    reset a reader cannot verify from Browse is a reset they cannot trust.
    """
    store = connect(Path(store_path))
    removed: list[str] = []
    try:
        for row in store.execute(
            "SELECT pack_id FROM packs ORDER BY pack_id"
        ).fetchall():
            packstore.uninstall(store, row["pack_id"])
            removed.append(row["pack_id"])
    finally:
        store.close()

    from app import packdraft
    from app.web import state

    root = packdraft.drafts_root(store_path)
    drafts: list[str] = []
    if root.is_dir():
        for one in sorted(root.iterdir()):
            if one.is_dir():
                shutil.rmtree(one, ignore_errors=True)
                drafts.append(one.name)
        for artifact in sorted(root.glob("*.kpack")):
            artifact.unlink(missing_ok=True)

    if app_state_path:
        conn = state.connect(Path(app_state_path))
        try:
            state.put_settings(conn, {RESET_KEY: True})
        finally:
            conn.close()
    return {"removed": removed, "drafts": drafts, "history_kept": True}


def was_reset(app_state_path) -> bool:
    """Whether this store was emptied on purpose and must not be reseeded."""
    if not app_state_path:
        return False
    from app.web import state

    try:
        conn = state.connect(Path(app_state_path))
    except sqlite3.Error:
        return False
    try:
        return bool(state.all_settings(conn).get(RESET_KEY))
    finally:
        conn.close()


def clear_reset(app_state_path) -> None:
    """Let seeding run again: the reader chose to rebuild, and finished."""
    if not app_state_path:
        return
    from app.web import state

    conn = state.connect(Path(app_state_path))
    try:
        conn.execute("DELETE FROM settings WHERE key = ?", (RESET_KEY,))
        conn.commit()
    finally:
        conn.close()
