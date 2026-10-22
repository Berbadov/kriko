"""Which program serves the local model, and a check that it answers.

`providers/local_runtimes.py` knows the programs and asks one address what it
lists; this is the door. What the reader picks (`local_runtime`) and the
address (`local_url`) are saved with the other settings through
`PUT /api/prefs`, so there is one place a preference is stored and validated.
Checking is a press: it asks the address once and installs nothing.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import prefs
from app.providers import local_runtimes
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/local-runtimes", tags=["local-runtimes"])


class RuntimeCheck(BaseModel):
    runtime: str = ""
    #: Empty means the program's conventional address.
    url: str = ""


@router.get("")
def read(conn=Depends(get_app_state)) -> dict:
    chosen = prefs.read(conn)
    return {"runtimes": local_runtimes.runtimes(),
            "chosen": chosen.get(prefs.LOCAL_RUNTIME, ""),
            "url": chosen.get(prefs.LOCAL_URL, "")}


@router.post("/check")
def check(body: RuntimeCheck, conn=Depends(get_app_state)) -> dict:
    """Does it answer, which models does it list, and what Kriko can set on it."""
    return local_runtimes.check(body.url, body.runtime.strip().casefold(), prefs.read(conn))
