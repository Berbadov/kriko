"""The research queue: products lined up from the browser extension.

The reader presses Add to queue on a listing; the panel posts the page's
address, the product's name and the stored answer's id when there is one. An
agent researches the queued products, as many at once as the reader's
Settings allow, and the compare screen lines them up. App state in `app.sqlite`, never knowledge: nothing in
`kriko/` reads it, and a pack update or uninstall leaves it alone.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.web import productchecks, state
from app.web.deps import get_app_state, get_store

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
    can say "already queued" instead of pretending to add it twice. Pressing
    again on a product already researched queues it again (`requeued: true`)."""
    try:
        item, added, requeued = state.queue_product(conn, body.url, body.name, body.lookup_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OverflowError as error:
        raise HTTPException(409, str(error)) from error
    items = state.research_queue(conn)
    return {"item": item, "added": added, "requeued": requeued,
            "count": len(items), "max": state.QUEUE_MAX}


class QueueUpdate(BaseModel):
    #: waiting | researching | done; absent leaves it as it is.
    state: str | None = Field(default=None, max_length=32)
    #: The stored answer made after researching, so Compare reads fresh claims.
    lookup_id: str | None = Field(default=None, max_length=64)
    #: Why the product was passed over, said in words; "" clears it.
    note: str | None = Field(default=None, max_length=600)


@router.patch("/{queue_id}")
def update_queued(queue_id: str, body: QueueUpdate, conn=Depends(get_app_state)) -> dict:
    """The window moves a product along as its research runs and finishes."""
    try:
        item = state.update_queued(
            conn, queue_id, state=body.state, lookup_id=body.lookup_id, note=body.note)
    except state.QueueConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if item is None:
        raise HTTPException(404, f"no queued product {queue_id}")
    return {"item": item}


@router.get("/{queue_id}/target")
def queue_target(queue_id: str, job_id: str = "", conn=Depends(get_app_state),
                 store=Depends(get_store)) -> dict:
    """The installed product a queued row stands for, resolved on the engine.

    Asked before a research starts, and again with `job_id` once a draft
    research has finished: then the product is the one that job produced. A
    product no catalog names is a 404 whose detail is the reason, and two that
    fit equally are a 409 naming both.
    """
    item = state.queued_item(conn, queue_id)
    if item is None:
        raise HTTPException(404, f"no queued product {queue_id}")
    job = None
    if job_id:
        job = state.get_job(conn, job_id)
        if job is None:
            raise HTTPException(404, f"no such job: {job_id}")
    try:
        return productchecks.resolve(conn, store, item, job)
    except productchecks.ProductNotFound as error:
        raise HTTPException(404, str(error)) from error
    except productchecks.ProductAmbiguous as error:
        raise HTTPException(409, str(error)) from error


@router.delete("/{queue_id}")
def remove_from_queue(queue_id: str, conn=Depends(get_app_state)) -> dict:
    if not state.unqueue_product(conn, queue_id):
        raise HTTPException(404, f"no queued product {queue_id}")
    return {"removed": queue_id}
