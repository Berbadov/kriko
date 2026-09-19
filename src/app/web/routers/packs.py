"""What is installed, and what it covers."""

import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi import Header
from pydantic import BaseModel, Field

from app import packdraft
from app.web.deps import get_store
from kriko.pack.scaffold import scaffold
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


class NewPack(BaseModel):
    """A pack about to exist, in the four fields the contract actually needs.

    `identity` is free-form on purpose — kind to attribute keys, whatever the
    author's category is shaped like. A typed field per kind would be this
    server having an opinion about what products are, which is the one thing
    G6 forbids.
    """

    root: str
    pack_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    identity: dict[str, list[str]] = Field(default_factory=dict)
    version: str = Field(default="0.1.0", max_length=40)


@router.post("/packs/scaffold")
def scaffold_pack(body: NewPack):
    """Write a new pack's skeleton to disk, ready to fill in and build.

    Authoring a pack was the one thing this app could not start: it could build
    a directory and install the artifact, but the directory itself had to be
    created by hand from a document. This closes that — the reader gets a
    contract-passing pack in one press and edits rows from there.

    Writes files and installs nothing. Building is a job, and the artifact only
    reaches the store when that job runs, so a mistake here costs a directory
    and never a store row.
    """
    root = Path(body.root).expanduser()
    if not str(root):
        raise HTTPException(400, "a directory is required")
    try:
        written = scaffold(
            root,
            pack_id=body.pack_id,
            name=body.name,
            identity=body.identity,
            version=body.version,
        )
    except FileExistsError as exc:
        # 409, not 400: the request was well formed and the conflict is with
        # the filesystem's current state — and the answer is a different
        # directory, not a corrected field. But Windows raises the same
        # exception when a *parent* of the root is a plain file, which is a
        # bad path rather than a conflict — so the conflict is named by
        # checking the one file the scaffold refuses to overwrite.
        if (root / "pack.toml").exists():
            raise HTTPException(409, str(exc)) from exc
        raise HTTPException(400, f"could not write to {root}: {exc}") from exc
    except NotADirectoryError as exc:
        raise HTTPException(400, f"could not write to {root}: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(400, f"could not write to {root}: {exc}") from exc
    return {"root": str(root), "files": [str(path) for path in written]}


# ── drafts an agent wrote ────────────────────────────────────────────────
#
# `app/packdraft.py` is the boundary; this is the reader's side of it. An agent
# can author a pack and build it, and nothing it writes reaches the store — so
# the store's side of that door has to exist somewhere the reader can see, and
# a directory under `~/.kriko/drafts` that nothing lists is a directory nobody
# installs.


class AmendRequest(BaseModel):
    """What is missing, in the reader's own words. Optional: with nothing said,
    the draft's own uncovered line-up is the request."""

    note: str = Field("", max_length=2000)
    harness: str = Field("", max_length=64)


@router.get("/packs/drafts")
def list_pack_drafts(request: Request):
    """Every drafted pack, whether it loads, and whether it has been built."""
    return {"items": packdraft.listing(request.app.state.settings.store_path)}


@router.post("/packs/drafts/{slug}/build")
def build_pack_draft(slug: str, request: Request):
    """Build a draft into an artifact without installing it."""
    try:
        out = packdraft.build_artifact(request.app.state.settings.store_path, slug)
    except packdraft.DraftRefused as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError) as exc:
        # The draft's own rows are wrong, which is a 400 about the draft rather
        # than a 500 about this app: the answer is an edit, and the agent that
        # wrote it is the one who makes it.
        raise HTTPException(400, f"this draft does not build: {exc}") from exc
    return {"slug": slug, "artifact": str(out)}


@router.post("/packs/drafts/{slug}/amend")
def amend_pack_draft(slug: str, request: Request, body: AmendRequest | None = None):
    """Ask an agent for what this draft is missing (B127). Returns a job id.

    The reader's sentence — "it has nineteen and lacks the twentieth" — as a
    button. Nothing already in the draft is rewritten, and a refused amendment
    leaves it exactly as it was, which is what makes this safe to press on a
    pack you already like.
    """
    runner = request.app.state.jobs
    try:
        job_id = runner.submit(
            "pack_amend",
            {"slug": slug, **(body.model_dump() if body else {"note": "", "harness": ""})},
        )
    except KeyError as exc:  # pragma: no cover - the handler is registered
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": job_id, "kind": "pack_amend", "slug": slug}


@router.get("/packs/drafts/{slug}")
def read_pack_draft(slug: str, request: Request):
    """What this draft holds, and what of its own line-up it does not cover.

    The gap list is the screen's reason to offer **Cover the gaps** at all: a
    button that asks for "whatever is missing" without showing what that is
    asks the reader to trust a number.
    """
    from app import packauthor

    try:
        return packauthor.draft_state(request.app.state.settings.store_path, slug)
    except packdraft.DraftRefused as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/packs/drafts/{slug}/install")
def install_pack_draft(slug: str, request: Request, store=Depends(get_store)):
    """Build the draft if needed, then install it. The reader's press.

    Built here rather than requiring a separate build first, because "install
    this" is one decision and a reader who has read the draft should not have
    to learn the artifact's lifecycle to act on it.
    """
    settings = request.app.state.settings
    try:
        artifact = packdraft.build_artifact(settings.store_path, slug)
    except packdraft.DraftRefused as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"this draft does not build: {exc}") from exc
    try:
        pack_id = packstore.install(store, artifact)
    except (ValueError, sqlite3.Error) as exc:
        raise HTTPException(400, f"invalid pack artifact: {exc}") from exc
    # Marked, not deleted (B129). The reader installed the Samsung draft, saw
    # the pack appear in Knowledge, and the "…was drafted for you" card stayed —
    # which reads as an install that did not take. Deleting the directory
    # instead would throw away the one copy of what the agent proposed, and
    # `Cover the gaps` still works on an installed draft: amend, rebuild,
    # install again.
    packdraft.mark_installed(settings.store_path, slug, pack_id)
    return {"slug": slug, "pack_id": pack_id, "installed": True}


@router.delete("/packs/drafts/{slug}")
def discard_pack_draft(slug: str, request: Request):
    """Throw a draft away. Only ever the reader's call.

    Nothing in the agent surface can delete a draft: an agent that wrote the
    wrong thing rewrites the file, and an agent that could remove the evidence
    of what it wrote would be worse than one that cannot. Installed packs are
    untouched — this deletes the directory and the artifact beside it, both of
    which only ever held what an agent proposed.
    """
    import shutil

    try:
        draft = packdraft.open_draft(request.app.state.settings.store_path, slug)
    except packdraft.DraftRefused as exc:
        raise HTTPException(404, str(exc)) from exc
    artifact = draft.artifact()
    shutil.rmtree(draft.root, ignore_errors=True)
    if artifact:
        Path(artifact).unlink(missing_ok=True)
    return {"slug": draft.slug, "discarded": True}
