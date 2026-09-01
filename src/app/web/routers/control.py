"""Operational views for the local web control plane."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.web.deps import get_store
from app.web.observability import load_records
from kriko.store import packstore

router = APIRouter(prefix="/api", tags=["control"])


def _row(row):
    return dict(row)


@router.get("/status")
def status(store=Depends(get_store)):
    """A small, data-driven snapshot suitable for a dashboard header."""
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
    packs = packstore.installed_packs(store)
    return {
        "ok": True,
        "packs": len(packs),
        "enabled_packs": sum(bool(p["enabled"]) for p in packs),
        "counts": counts,
    }


@router.get("/activity")
def activity(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
):
    """Most recent analysis requests, newest first, from the JSONL log."""
    records, skipped = load_records(request.app.state.settings.analysis_log_path)
    records.reverse()
    return {"items": records[:limit], "malformed": skipped}


@router.get("/packs/{pack_id}/revisions")
def revisions(pack_id: str, store=Depends(get_store)):
    if not store.execute(
        "SELECT 1 FROM packs WHERE pack_id = ?", (pack_id,)
    ).fetchone():
        raise HTTPException(404, f"pack not installed: {pack_id}")
    active = store.execute(
        "SELECT content_digest FROM packs WHERE pack_id = ?", (pack_id,)
    ).fetchone()["content_digest"]
    return [
        {**_row(row), "active": row["content_digest"] == active}
        for row in packstore.revisions(store, pack_id)
    ]


@router.get("/packs/{pack_id}/events")
def events(pack_id: str, store=Depends(get_store)):
    if not store.execute(
        "SELECT 1 FROM packs WHERE pack_id = ?", (pack_id,)
    ).fetchone():
        raise HTTPException(404, f"pack not installed: {pack_id}")
    out = []
    for row in packstore.events(store, pack_id):
        item = _row(row)
        item["details"] = json.loads(item.pop("details_json") or "{}")
        out.append(item)
    return out


@router.post("/packs/{pack_id}/activate")
def activate(pack_id: str, revision: str | None = None, store=Depends(get_store)):
    try:
        packstore.activate(store, pack_id, revision)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"pack_id": pack_id, "activated": True, "revision": revision}


@router.post("/packs/{pack_id}/rollback")
def rollback(pack_id: str, revision: str | None = None, store=Depends(get_store)):
    try:
        packstore.rollback(store, pack_id, revision)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"pack_id": pack_id, "rolled_back": True, "revision": revision}


@router.post("/packs/{pack_id}/revisions/{revision_id}/activate")
def activate_revision(pack_id: str, revision_id: str, store=Depends(get_store)):
    return activate(pack_id, revision_id, store)


@router.post("/packs/{pack_id}/revisions/{revision_id}/rollback")
def rollback_revision(pack_id: str, revision_id: str, store=Depends(get_store)):
    return rollback(pack_id, revision_id, store)
