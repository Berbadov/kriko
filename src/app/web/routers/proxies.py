"""The proxy pool for blocked page reads: what is set, what was measured, a check.

Off by default (`providers/proxypool.py` says what it does and does not do).
The switch and the pool's addresses are saved through `PUT /api/prefs` with the
other settings and the login through `PUT /api/keys`, so each is stored and
validated in one place. This is the read side and one press: Check asks each
saved proxy for a single small public page.
"""

from fastapi import APIRouter, Depends

from app.providers import proxypool
from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


@router.get("")
def read(conn=Depends(get_app_state)) -> dict:
    return proxypool.status(conn)


@router.post("/check")
def check(conn=Depends(get_app_state)) -> dict:
    """Does each saved proxy connect, with the saved login, and how fast."""
    pool = proxypool.parse_pool(str(state.all_settings(conn).get(proxypool.SETTING_POOL) or ""))
    return {"results": proxypool.check(pool) if pool else [],
            "message": "" if pool else "Add at least one proxy address first."}
