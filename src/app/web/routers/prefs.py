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

from app import costs, prefs, scale
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
    #: One per stage of a run, each falling back to `llm_model`. Spelled out
    #: rather than accepted as a free-form mapping, because a settings writer
    #: that took arbitrary keys would let a browser on localhost write any
    #: row it liked into this installation's settings — the same reasoning
    #: `app/keys.py` gives for naming its providers instead of accepting
    #: `KEY=value`.
    llm_model_plan: str | None = Field(None, max_length=200)
    llm_model_extract: str | None = Field(None, max_length=200)
    llm_model_synthesise: str | None = Field(None, max_length=200)
    llm_model_validate: str | None = Field(None, max_length=200)


@router.get("/prefs")
def read_prefs(conn=Depends(get_app_state)) -> dict:
    return prefs.choices(conn)


@router.put("/prefs")
def write_prefs(body: PrefsWrite, conn=Depends(get_app_state)) -> dict:
    written = {key: value for key, value in body.model_dump().items()
               if value is not None}
    prefs.write(conn, written)
    return prefs.choices(conn)


@router.get("/scales")
def read_scales(conn=Depends(get_app_state)) -> dict:
    """Every position on the depth dial, with what each is likely to cost here.

    Served with the estimate attached rather than as a bare list, because the
    reader asked for exactly one thing — to know that fifteen sources costs
    more than three *before* choosing — and a list of names would be the same
    unanswerable choice the knobs already were.
    """
    return {"scales": scale.offered(conn), "default": scale.DEFAULT}


@router.get("/costs")
def read_costs(conn=Depends(get_app_state)) -> dict:
    """What has been spent here, what the next run is likely to cost, and why
    there is no credit balance on this screen."""
    return costs.overview(conn)
