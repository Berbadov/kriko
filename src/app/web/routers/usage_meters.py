"""What the app has used, by resource and by rolling window.

`GET /api/usage/meters` is the one read the top bar's usage pill and its detail
card draw from (`app/usage.py` says what each number is and when it is blank).
It is a separate path from `GET /api/usage`, which sums research runs only.
"""

from fastapi import APIRouter, Depends

from app import usage
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/meters")
def meters(conn=Depends(get_app_state)) -> dict:
    return usage.meters(conn)
