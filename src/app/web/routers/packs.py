"""What is installed, and what it covers."""

import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from app.web.deps import get_store
from kriko.store import packstore

router = APIRouter(prefix="/api", tags=["packs"])


@router.post("/packs/install")
def install_pack(
    body: bytes = Body(default=b""),
    filename: str | None = Query(default=None),
    filename_header: str | None = Header(default=None, alias="X-Filename"),
    store=Depends(get_store),
):
    """Install one uploaded artifact without accepting a filesystem path.

    The browser sends the artifact as the request body. The optional filename is
    metadata only; the store always receives a generated temporary path.
    """
    if not body:
        raise HTTPException(400, "pack artifact is empty")

    supplied_name = filename or filename_header or "upload.kpack"
    if (
        Path(supplied_name).name != supplied_name
        or "\\" in supplied_name
        or supplied_name in {".", ".."}
    ):
        raise HTTPException(400, "filename must be a plain file name")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".kpack", delete=False) as staged:
            staged.write(body)
            temporary_path = Path(staged.name)
        try:
            pack_id = packstore.install(store, temporary_path)
        except ValueError as exc:
            raise HTTPException(400, f"invalid pack artifact: {exc}") from exc
        except sqlite3.Error as exc:
            raise HTTPException(400, "invalid pack artifact") from exc

        pack = store.execute(
            "SELECT * FROM packs WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        revision = packstore.revisions(store, pack_id)[0]
        counts = {
            table: store.execute(
                f"SELECT COUNT(*) FROM {table} WHERE pack_id = ?", (pack_id,)
            ).fetchone()[0]
            for table in ("subjects", "claims", "evidence")
        }
        return {
            "pack": {
                "pack_id": pack["pack_id"],
                "name": pack["name"],
                "version": pack["version"],
                "enabled": bool(pack["enabled"]),
            },
            "revision": dict(revision),
            "counts": counts,
        }
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(500, "could not stage pack artifact") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


@router.get("/packs")
def list_packs(store=Depends(get_store)):
    rows = packstore.installed_packs(store)
    out = []
    for row in rows:
        counts = {
            table: store.execute(
                f"SELECT COUNT(*) FROM {table} WHERE pack_id = ?", (row["pack_id"],)
            ).fetchone()[0]
            for table in ("subjects", "claims", "evidence")
        }
        out.append(
            {
                "pack_id": row["pack_id"],
                "name": row["name"],
                "version": row["version"],
                "publisher": row["publisher"],
                "license": row["license"],
                "origin_url": row["origin_url"],
                "enabled": bool(row["enabled"]),
                "installed_at": row["installed_at"],
                "trust_weight": row["trust_weight"],
                "digest": row["content_digest"][:12],
                **counts,
            }
        )
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
    return [
        dict(r)
        for r in store.execute(
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
            " ORDER BY s.label LIMIT ?",
            (pack_id, limit),
        )
    ]


@router.get("/packs/{pack_id}/vocabulary")
def vocabulary(pack_id: str, store=Depends(get_store)):
    """The pack's own words — what a category costs instead of code."""
    terms = [
        dict(r)
        for r in store.execute(
            "SELECT term_id, role, datatype, unit FROM terms"
            " WHERE pack_id = ? ORDER BY role, term_id",
            (pack_id,),
        )
    ]
    by_role: dict[str, list] = {}
    for term in terms:
        by_role.setdefault(term["role"], []).append(term)
    return by_role
