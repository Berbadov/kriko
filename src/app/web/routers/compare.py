"""Saved comparisons: the reader's named shortlists of checks (B183).

App state in `app.sqlite`, never knowledge: nothing in `kriko/` reads it, and a
pack update or uninstall leaves it alone. A draft holds only which checks, in
which order; the screen reads the checks themselves from `/api/lookup`.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/compare-drafts", tags=["compare"])


class DraftRequest(BaseModel):
    name: str = Field(max_length=200)
    lookup_ids: list[str] = Field(default_factory=list, max_length=20)


@router.get("")
def list_drafts(conn=Depends(get_app_state)) -> dict:
    return {"items": state.compare_drafts(conn), "max": state.COMPARE_MAX}


@router.post("")
def create_draft(body: DraftRequest, conn=Depends(get_app_state)) -> dict:
    try:
        return state.save_compare_draft(conn, body.name, body.lookup_ids)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.put("/{draft_id}")
def update_draft(draft_id: str, body: DraftRequest,
                 conn=Depends(get_app_state)) -> dict:
    try:
        return state.save_compare_draft(conn, body.name, body.lookup_ids, draft_id)
    except KeyError as error:
        raise HTTPException(404, f"no draft {draft_id}") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.delete("/{draft_id}")
def delete_draft(draft_id: str, conn=Depends(get_app_state)) -> dict:
    if not state.delete_compare_draft(conn, draft_id):
        raise HTTPException(404, f"no draft {draft_id}")
    return {"deleted": draft_id}
