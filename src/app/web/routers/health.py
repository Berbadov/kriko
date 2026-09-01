"""How well supported is what we ship?

The other side of the coverage report. `/api/packs/{id}/gaps` answers absence
— subjects nobody has researched. This answers weakness — claims that are
shipped on one forum post, or that we hold a rebuttal to. Both are needed: a
researcher with no weakness view can only ever add, never repair.

Read-only, and deliberately so. Nothing here writes, and no ranking the reader
sees is changed by it.

Serialisation is `kriko.lookup.tree.health_json`/`tree_json` — reused rather
than re-implemented, so this router and the MCP server carry no second copy
of the same shape.
"""

from fastapi import APIRouter, Depends

from app.web.deps import get_store
from kriko.lookup.tree import health_json, subject_tree, tree_json, weakest_claims

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/weakest")
def weakest(limit: int = 20, pack_id: str = "", store=Depends(get_store)):
    """The shipped claims that are least well supported, worst first.

    Claims with **no** evidence at all are excluded, not ranked last: absence
    is a coverage question (see `/api/packs/{id}/gaps`), not a weakness one.
    A negative `limit` is clamped to zero rather than erroring or inverting
    the slice.
    """
    packs = [pack_id] if pack_id else None
    return {"claims": [health_json(h)
                       for h in weakest_claims(store, packs, limit=limit)]}


@router.get("/subject/{subject_id}")
def subject(subject_id: str, store=Depends(get_store)):
    """An unknown subject is an empty tree, not a 404.

    Unlike `/api/subjects/{id}`, which 404s because the caller asked for a
    thing that does not exist, this endpoint answers a question about health —
    and "nothing known" is a valid answer to it.
    """
    return tree_json(subject_tree(store, subject_id))
