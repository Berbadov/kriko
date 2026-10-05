"""The research queue: products lined up from the browser extension.

The reader presses Add to queue on a listing; the panel posts the page's
address, the product's name and the stored answer's id when there is one. An
agent researches the queued products one after another and the compare
screen lines them up. App state in `app.sqlite`, never knowledge: nothing in
`kriko/` reads it, and a pack update or uninstall leaves it alone.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/queue", tags=["queue"])


class QueueRequest(BaseModel):
    url: str = Field(max_length=2000)
    name: str = Field(default="", max_length=400)
    lookup_id: str = Field(default="", max_length=64)


@router.get("")
def list_queue(conn=Depends(get_app_state)) -> dict:
    return {"items": state.research_queue(conn), "max": state.QUEUE_MAX}


@router.post("")
def add_to_queue(body: QueueRequest, conn=Depends(get_app_state)) -> dict:
    """Queue one product. Pressing again on the same page is not an error:
    it answers with the row already there and `added: false`, so the panel
    can say "already queued" instead of pretending to add it twice."""
    try:
        item, added = state.queue_product(conn, body.url, body.name, body.lookup_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OverflowError as error:
        raise HTTPException(409, str(error)) from error
    items = state.research_queue(conn)
    return {"item": item, "added": added, "count": len(items), "max": state.QUEUE_MAX}


class QueueUpdate(BaseModel):
    #: waiting | researching | done; absent leaves it as it is.
    state: str | None = Field(default=None, max_length=32)
    #: The stored answer made after researching, so Compare reads fresh claims.
    lookup_id: str | None = Field(default=None, max_length=64)


@router.patch("/{queue_id}")
def update_queued(queue_id: str, body: QueueUpdate, conn=Depends(get_app_state)) -> dict:
    """The window moves a product along as its research runs and finishes."""
    try:
        item = state.update_queued(
            conn, queue_id, state=body.state, lookup_id=body.lookup_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if item is None:
        raise HTTPException(404, f"no queued product {queue_id}")
    return {"item": item}


@router.delete("/{queue_id}")
def remove_from_queue(queue_id: str, conn=Depends(get_app_state)) -> dict:
    if not state.unqueue_product(conn, queue_id):
        raise HTTPException(404, f"no queued product {queue_id}")
    return {"removed": queue_id}
