"""Past answers, so a reload is not a loss.

Reads and writes `app.sqlite` only. Nothing here touches the knowledge store,
and nothing here changes a ranking — this router is the UI's memory, not the
engine's.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.web import state, tasks
from app.web.deps import get_app_state, get_jobs, get_store

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
def history(
    limit: int = Query(20, ge=1, le=200),
    app_state=Depends(get_app_state),
    store=Depends(get_store),
):
    """Recent checks, each with the category its pack names (B182).

    The category is the name of the pack that answered, read from the engine
    store at request time so a renamed or uninstalled pack is reflected
    rather than frozen into a stored row. A check no pack answered has an
    empty category, and the screen names that group itself.
    """
    items = state.recent(app_state, limit)
    names = {
        row["pack_id"]: row["name"]
        for row in store.execute("SELECT pack_id, name FROM packs")
    }
    for item in items:
        ids = item.pop("pack_ids")
        subject_ids = item.pop("subject_ids")
        if not ids and subject_ids:
            # A check that matched a product but found no risk names no pack
            # in its claims; the product it matched still belongs to one.
            marks = ",".join("?" * len(subject_ids))
            ids = [
                row["pack_id"]
                for row in store.execute(
                    "SELECT DISTINCT pack_id FROM subjects"
                    f" WHERE subject_id IN ({marks}) ORDER BY pack_id",
                    subject_ids,
                )
            ]
        item["packs"] = [{"pack_id": i, "name": names[i]} for i in ids if i in names]
        item["category"] = item["packs"][0]["name"] if item["packs"] else ""
    return {"items": items}


@router.get("/lookup/{lookup_id}")
def get_lookup(lookup_id: str, app_state=Depends(get_app_state)):
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return row


class FollowupRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.get("/lookup/{lookup_id}/questions")
def lookup_questions(lookup_id: str, app_state=Depends(get_app_state)):
    if state.get_lookup(app_state, lookup_id) is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    return {"items": state.lookup_questions(app_state, lookup_id)}


@router.post("/lookup/{lookup_id}/questions")
def ask_lookup(lookup_id: str, body: FollowupRequest,
               app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    if state.get_lookup(app_state, lookup_id) is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Write a question first.")
    params = {"lookup_id": lookup_id, "question": question,
              "backend": tasks.default_backend(runner.settings.app_state_path),
              "budget_usd": tasks.DEFAULT_BUDGET_USD}
    return {"job_id": runner.submit("lookup_ask", params), "kind": "lookup_ask"}


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

class Note(BaseModel):
    claim_key: str
    #: Bounded, and generously: this is where "belt done at 140k per the
    #: seller, receipt promised" goes. The cap exists so a paste of an entire
    #: listing cannot become a history row.
    note: str = Field(default="", max_length=4000)


@router.get("/lookups/{lookup_id}/triage")
def read_triage(lookup_id: str, app_state=Depends(get_app_state)):
    """Both halves of the reader's own marks on one answer, in one request.

    The checkmarks and the notes are read together because they are rendered
    together: two requests for one screen means a report that paints its
    checkboxes and then, a moment later, its notes.
    """
    return {
        "lookup_id": lookup_id,
        "checked": state.checked_keys(app_state, lookup_id),
        "notes": state.notes(app_state, lookup_id),
    }


@router.post("/lookups/{lookup_id}/notes")
def write_note(lookup_id: str, body: Note, app_state=Depends(get_app_state)):
    """Record what the seller said about one risk.

    Same tolerance as `write_checked`: a note for a lookup that has since been
    forgotten is stored rather than refused, because the reader's own words are
    the last thing this app should be losing to a race.
    """
    return {
        "lookup_id": lookup_id,
        "notes": state.set_note(app_state, lookup_id, body.claim_key, body.note),
    }
