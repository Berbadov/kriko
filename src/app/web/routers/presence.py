"""The optional anonymous presence ping's status, for the Usage settings page.

`GET` only reads: whether the reader opted in, where a ping would go, and the
last day one was sent. Turning it on or off is an ordinary preference write
through `/api/prefs` (`presence_enabled`); this endpoint exists so the screen
can say what the choice means without a second vocabulary.
"""

from fastapi import APIRouter, Depends, Request

from app import presence
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/presence", tags=["presence"])


@router.get("")
def status(request: Request, conn=Depends(get_app_state)) -> dict:
    return presence.status(conn, request.app.state.settings.presence_endpoint)
