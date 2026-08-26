"""What is installed, and what it covers."""

from fastapi import APIRouter, Depends, HTTPException

from apps.web.deps import get_store
from kriko.store import packstore

router = APIRouter(prefix="/api", tags=["packs"])


@router.get("/packs")
def list_packs(store=Depends(get_store)):
    rows = packstore.installed_packs(store)
    out = []
    for row in rows:
        counts = {
            table: store.execute(
                f"SELECT COUNT(*) FROM {table} WHERE pack_id = ?",
                (row["pack_id"],)).fetchone()[0]
            for table in ("subjects", "claims", "evidence")
        }
        out.append({
            "pack_id": row["pack_id"], "name": row["name"],
            "version": row["version"], "publisher": row["publisher"],
            "license": row["license"], "origin_url": row["origin_url"],
            "enabled": bool(row["enabled"]), "installed_at": row["installed_at"],
            "trust_weight": row["trust_weight"],
            "digest": row["content_digest"][:12],
            **counts,
        })
    return out


@router.post("/packs/{pack_id}/enabled")
def set_enabled(pack_id: str, enabled: bool = True, store=Depends(get_store)):
    try:
        packstore.set_enabled(store, pack_id, enabled)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"pack_id": pack_id, "enabled": enabled}


@router.delete("/packs/{pack_id}")
def uninstall(pack_id: str, store=Depends(get_store)):
    """Remove a pack. Every other pack is untouched — that is the whole point
    of `pack_id` living in every primary key."""
    try:
        packstore.uninstall(store, pack_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"pack_id": pack_id, "uninstalled": True}


@router.get("/packs/{pack_id}/gaps")
def coverage_gaps(pack_id: str, limit: int = 100, store=Depends(get_store)):
    """Subjects nobody has researched yet.

    A gap is not an error and stops nothing — that is the fail-open rule. But it
    has to be *findable* without a person noticing, or fail-open quietly becomes
    fail-silent.
    """
    # A subject is only a gap when nothing reaches it — including through the
    # parts it is built from. Counting direct claims alone would report every
    # car in the catalog as unresearched, because a car's claims live on its
    # engine and gearbox, not on the car.
    return [dict(r) for r in store.execute(
        "SELECT s.subject_id, s.kind, s.label FROM subjects s"
        " WHERE s.pack_id = ?"
        "   AND NOT EXISTS (SELECT 1 FROM claims c"
        "                   WHERE c.subject_id = s.subject_id"
        "                     AND c.pack_id = s.pack_id)"
        "   AND NOT EXISTS (SELECT 1 FROM relations r"
        "                   JOIN claims c2 ON c2.subject_id = r.object_id"
        "                                 AND c2.pack_id = r.pack_id"
        "                   WHERE r.subject_id = s.subject_id"
        "                     AND r.pack_id = s.pack_id)"
        " ORDER BY s.label LIMIT ?", (pack_id, limit))]


@router.get("/packs/{pack_id}/vocabulary")
def vocabulary(pack_id: str, store=Depends(get_store)):
    """The pack's own words — what a category costs instead of code."""
    terms = [dict(r) for r in store.execute(
        "SELECT term_id, role, datatype, unit FROM terms"
        " WHERE pack_id = ? ORDER BY role, term_id", (pack_id,))]
    by_role: dict[str, list] = {}
    for term in terms:
        by_role.setdefault(term["role"], []).append(term)
    return by_role
