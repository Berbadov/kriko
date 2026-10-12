"""Operational views for the local web control plane."""

from fastapi import APIRouter, Depends

from app.web.deps import get_store
from kriko.store import packstore

router = APIRouter(prefix="/api", tags=["control"])


@router.get("/status")
def status(store=Depends(get_store)):
    """A small, data-driven snapshot suitable for an app header."""
    counts = {}
    for table in (
        "packs",
        "subjects",
        "claims",
        "evidence",
        "pack_revisions",
        "pack_events",
    ):
        counts[table] = store.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    # Disabling a pack takes its claims out of every lookup, so a header that
    # still quotes the disabled pack's rows reads as a bigger knowledge base
    # than the reader can actually get an answer from (knowledge-36). Every
    # row-bearing table carries pack_id, so this is a join, not a guess.
    counts_enabled = {}
    for table in ("subjects", "claims", "evidence"):
        counts_enabled[table] = store.execute(
            f"""
            SELECT COUNT(*) FROM {table} t
            JOIN packs p ON p.pack_id = t.pack_id
            WHERE p.enabled
            """
        ).fetchone()[0]
    packs = packstore.installed_packs(store)
    return {
        "ok": True,
        "packs": len(packs),
        "enabled_packs": sum(bool(p["enabled"]) for p in packs),
        "counts": counts,
        "counts_enabled": counts_enabled,
    }
