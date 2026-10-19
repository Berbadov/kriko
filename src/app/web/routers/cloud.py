"""The relay, from the reader's side: connect, pair a phone, sync, and choose what the relay watches.

App state only (`app/cloud.py`). Nothing here reads the knowledge store. The pairing
code is the reader's key, so it is returned only by the one route that is asked for
it, and never by `status`.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import cloud, pricewatch
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


def _refuse(error: Exception) -> HTTPException:
    if isinstance(error, cloud.RelayError):
        return HTTPException(502, str(error))
    return HTTPException(422, str(error))


@router.get("")
def status(conn=Depends(get_app_state)) -> dict:
    return {**cloud.status(conn), "suggested_server": cloud.default_server()}


class ConnectRequest(BaseModel):
    server_url: str = Field(max_length=300)
    #: Tell the relay a watched page's address and price, never what the product is called.
    private_labels: bool = False


@router.post("/connect")
def connect(body: ConnectRequest, conn=Depends(get_app_state)) -> dict:
    try:
        return cloud.connect(conn, body.server_url, private_labels=body.private_labels)
    except (ValueError, cloud.RelayError) as error:
        raise _refuse(error) from error


class JoinRequest(BaseModel):
    code: str = Field(max_length=600)


@router.post("/join")
def join(body: JoinRequest, conn=Depends(get_app_state)) -> dict:
    try:
        return cloud.join(conn, body.code)
    except (ValueError, cloud.RelayError) as error:
        raise _refuse(error) from error


@router.get("/pairing")
def pairing(conn=Depends(get_app_state)) -> dict:
    """The code that lets a phone or another computer join. It is the key: show it only on request."""
    try:
        code = cloud.code_for(conn)
    except ValueError as error:
        raise _refuse(error) from error
    return {"code": code, "topic": cloud.status(conn)["topic"]}


@router.post("/sync")
def sync(conn=Depends(get_app_state)) -> dict:
    try:
        return cloud.sync(conn)
    except (ValueError, cloud.RelayError) as error:
        raise _refuse(error) from error


class WatchToggle(BaseModel):
    on: bool


@router.post("/watches/{watch_id}")
def watch_in_the_cloud(watch_id: str, body: WatchToggle, conn=Depends(get_app_state)) -> dict:
    """Let the relay watch this page while the computer is off. It learns the page when this is on."""
    if body.on and not cloud.configured(conn):
        raise HTTPException(422, "connect to a relay first")
    row = pricewatch.set_cloud(conn, watch_id, body.on)
    if row is None:
        raise HTTPException(404, f"no watch {watch_id}")
    synced = cloud.sync_quietly(conn)
    return {**row, "synced": synced is not None}


@router.delete("")
def disconnect(conn=Depends(get_app_state)) -> dict:
    cloud.disconnect(conn)
    return cloud.status(conn)
