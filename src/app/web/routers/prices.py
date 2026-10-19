"""Price memory, watches, and the look before paying.

App state in `app.sqlite`, never knowledge (`app/pricewatch.py`,
`app/checkout.py`). A price here is the page's own figure on a day the reader
looked, or a day a watch re-read the page; nothing is converted or invented.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import checkout, cloud, pricewatch
from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/page")
def page(url: str = Query(max_length=2000), name: str = Query(default="", max_length=300),
         conn=Depends(get_app_state)) -> dict:
    """What Kriko remembers about one page: its price line, its watch, and the same product elsewhere."""
    series = pricewatch.series(conn, url)
    latest = series[-1] if series else None
    elsewhere = pricewatch.elsewhere(conn, name, url, (latest or {}).get("currency", "")) if name else []
    return {"series": series, "watch": pricewatch.watch_for(conn, url),
            "elsewhere": [{"host": one["host"], "url": one["url"], "price": one["price"],
                           "currency": one["currency"], "seen_at": one["seen_at"]} for one in elsewhere[:5]]}


class WatchRequest(BaseModel):
    url: str = Field(max_length=2000)
    name: str = Field(default="", max_length=300)
    target: float | str | None = None
    drop_pct: float | str | None = None
    price: float | str | None = None
    currency: str = Field(default="", max_length=8)
    #: Also let the relay watch it while this computer is off. Only honoured when paired.
    cloud: bool | None = None


def _resync(request: Request):
    """A watch changed: tell the relay soon, off the request, and never fail the reader for it."""
    def run() -> None:
        conn = state.connect(request.app.state.settings.app_state_path)
        try:
            cloud.sync_quietly(conn)
        finally:
            conn.close()
    return run


@router.get("/watches")
def list_watches(conn=Depends(get_app_state)) -> dict:
    return {"items": pricewatch.watches(conn), "max": pricewatch.MAX_WATCHES,
            "alerts": pricewatch.alerts(conn)}


@router.post("/watches")
def add_watch(body: WatchRequest, request: Request, background: BackgroundTasks,
              conn=Depends(get_app_state)) -> dict:
    """Keep an eye on a page. Asking again for the same page changes its terms."""
    if body.cloud and not cloud.configured(conn):
        raise HTTPException(422, "connect to a relay first")
    try:
        made = pricewatch.watch(conn, body.url, body.name, target=body.target, drop_pct=body.drop_pct,
                                price=body.price, currency=body.currency, cloud=body.cloud)
        if cloud.configured(conn):
            background.add_task(_resync(request))
        return made
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except OverflowError as error:
        raise HTTPException(409, str(error)) from error


@router.delete("/watches/{watch_id}")
def stop_watch(watch_id: str, request: Request, background: BackgroundTasks,
               conn=Depends(get_app_state)) -> dict:
    if not pricewatch.unwatch(conn, watch_id):
        raise HTTPException(404, f"no watch {watch_id}")
    if cloud.configured(conn):
        background.add_task(_resync(request))
    return {"deleted": watch_id}


@router.get("/alerts")
def unread_alerts(conn=Depends(get_app_state)) -> dict:
    return {"items": pricewatch.alerts(conn)}


class ReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)


@router.post("/alerts/read")
def mark_alerts_read(body: ReadRequest, conn=Depends(get_app_state)) -> dict:
    return {"read": pricewatch.read_alerts(conn, body.ids or None)}


@router.post("/sweep")
def sweep_now(request: Request, conn=Depends(get_app_state)) -> dict:
    """Re-read the watched pages that are due, as a job. Nothing due is no job.

    The extension asks on a timer and the app asks on start; a page is read at
    most every few hours however often this is called.
    """
    due = pricewatch.due(conn)
    if not due:
        return {"job_id": "", "due": 0}
    return {"job_id": request.app.state.jobs.submit("price_sweep", {}), "due": len(due)}


class CartLine(BaseModel):
    name: str = Field(max_length=300)
    price: float | str | None = None
    currency: str = Field(default="", max_length=8)
    url: str = Field(default="", max_length=2000)


class CheckoutRequest(BaseModel):
    url: str = Field(max_length=2000)
    items: list[CartLine] = Field(default_factory=list, max_length=20)
    #: The page's visible text, trimmed by the extension; searched for return terms and payment methods.
    text: str = Field(default="", max_length=20000)


@router.post("/checkout")
def look_before_paying(body: CheckoutRequest, conn=Depends(get_app_state)) -> dict:
    return checkout.guard(conn, url=body.url, text=body.text,
                          items=[one.model_dump() for one in body.items])
