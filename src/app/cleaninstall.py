"""A clean install, rebuilt by the new flow (B188, decision D4).

The reader's sentence: "Remove every package so you can rebuild them." One
confirmed action does two things:

1. every installed pack is uninstalled, through `packstore.uninstall`, the
   same path as the per-pack button, so every dependent row goes with it;
2. every draft is discarded, because `~/.kriko/drafts/<slug>/` blocks a new
   draft of the same name ("drafts/x already holds a pack.toml").

History and settings are kept, per D4: history rows refer to packs by id, and
a lookup of a removed pack says so rather than pretending it never existed.

The installer carries no packs (#169), so nothing reinstalls what this removes
at the next start. Packs come back only when the reader installs them again.
"""

import shutil
from pathlib import Path

from kriko.store import packstore
from kriko.store.db import connect


def reset(store_path) -> dict:
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

    root = packdraft.drafts_root(store_path)
    drafts: list[str] = []
    if root.is_dir():
        for one in sorted(root.iterdir()):
            if one.is_dir():
                shutil.rmtree(one, ignore_errors=True)
                drafts.append(one.name)
        for artifact in sorted(root.glob("*.kpack")):
            artifact.unlink(missing_ok=True)
    return {"removed": removed, "drafts": drafts, "history_kept": True}
