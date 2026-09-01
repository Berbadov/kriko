"""Past answers, so a reload is not a loss.

Reads and writes `app.sqlite` only. Nothing here touches the knowledge store,
and nothing here changes a ranking — this router is the UI's memory, not the
engine's.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["history"])


def label_for(identity: dict, fallback: str = "lookup") -> str:
    """A human-readable name for a lookup.

    Built from whatever the pack's identity keys happen to be: the engine has
    no title for a query, and this must stay true for any category, so the
    values are joined in the order the caller sent them rather than picked by
    name. Naming a key here would be the hardcoded-list bug in a new place.
    """
    values = [str(v) for v in identity.values() if str(v).strip()]
    return " ".join(values) or fallback


@router.get("/history")
def history(limit: int = Query(20, ge=1, le=200), app_state=Depends(get_app_state)):
    return {"items": state.recent(app_state, limit)}


@router.get("/lookup/{lookup_id}")
def get_lookup(lookup_id: str, app_state=Depends(get_app_state)):
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return row


@router.delete("/history/{lookup_id}")
def forget(lookup_id: str, app_state=Depends(get_app_state)):
    if not state.delete_lookup(app_state, lookup_id):
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return {"deleted": True, "lookup_id": lookup_id}


class SettingsPatch(BaseModel):
    """Whatever the interface wants remembered.

    Free-form on purpose: `mode` is the only key today, and the backend has no
    business knowing that buyer/author exist — the projection is a frontend
    concern (see the design doc, decision 3). A typed field per preference
    would make every new UI toggle a backend change.
    """

    values: dict = Field(default_factory=dict)


@router.get("/settings")
def read_settings(app_state=Depends(get_app_state)):
    return state.all_settings(app_state)


@router.post("/settings")
def write_settings(body: SettingsPatch, app_state=Depends(get_app_state)):
    return state.put_settings(app_state, body.values)


class Check(BaseModel):
    claim_key: str
    checked: bool = True


@router.get("/lookups/{lookup_id}/checked")
def read_checked(lookup_id: str, app_state=Depends(get_app_state)):
    return {"lookup_id": lookup_id, "checked": state.checked_keys(app_state, lookup_id)}


@router.post("/lookups/{lookup_id}/checked")
def write_checked(lookup_id: str, body: Check, app_state=Depends(get_app_state)):
    """Mark one risk handled.

    Accepts a key for a lookup that no longer exists rather than 404ing: the
    checkmark is the reader's own note, and losing it to a race with a
    `DELETE /api/history` would be worse than storing an orphan row that the
    delete path already cleans up.
    """
    return {
        "lookup_id": lookup_id,
        "checked": state.set_checked(app_state, lookup_id, body.claim_key, body.checked),
    }
