"""What the reader chose, and what it costs.

Two endpoints, one screen. `app/prefs.py` holds the choices — which agent,
which model, which search provider — and `app/costs.py` holds what has been
spent and what the next run is likely to cost. They are served together
because at the moment of choosing a plane they are the same decision, and a
preference a reader sets without being shown the bill is how a surprise
happens.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import costs, prefs
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["prefs"])


class PrefsWrite(BaseModel):
    """Every field optional, and empty means "whatever the machine offers".

    Not a required set: a reader with one CLI installed should never have to
    name it, and an installation that has never opened this screen must behave
    exactly as it did before the screen existed.
    """

    preferred_harness: str | None = Field(None, max_length=64)
    llm_model: str | None = Field(None, max_length=200)
    search_provider: str | None = Field(None, max_length=64)


@router.get("/prefs")
def read_prefs(conn=Depends(get_app_state)) -> dict:
    return prefs.choices(conn)


@router.put("/prefs")
def write_prefs(body: PrefsWrite, conn=Depends(get_app_state)) -> dict:
    written = {key: value for key, value in body.model_dump().items()
               if value is not None}
    prefs.write(conn, written)
    return prefs.choices(conn)


@router.get("/costs")
def read_costs(conn=Depends(get_app_state)) -> dict:
    """What has been spent here, what the next run is likely to cost, and why
    there is no credit balance on this screen."""
    return costs.overview(conn)
