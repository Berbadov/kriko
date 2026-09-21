"""What the reader chose, and what it costs.

Two endpoints, one screen. `app/prefs.py` holds the choices — which agent,
which model, which search provider — and `app/costs.py` holds what has been
spent and what the next run is likely to cost. They are served together
because at the moment of choosing a plane they are the same decision, and a
preference a reader sets without being shown the bill is how a surprise
happens.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app import costs, prefs, scale
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["prefs"])


#: The longest a stored preference may be. One bound for all of them: every
#: value here is a short name — a harness id, a model id, an effort level.
VALUE_MAX = 200


class PrefsWrite(BaseModel):
    """Every field optional, and empty means "whatever the machine offers".

    Not a required set: a reader with one CLI installed should never have to
    name it, and an installation that has never opened this screen must behave
    exactly as it did before the screen existed.

    **The accepted keys are `prefs.KEYS`, not a list written out here.** They
    used to be a hand-written eleven, and that list named three harnesses out
    of five with no effort key at all — so a model chosen for Mistral Vibe or
    Gemini CLI was dropped by this schema before `prefs.write` ever saw it, and
    the effort dial was dead end to end. Nothing reported a failure: the screen
    re-renders from this endpoint's own reply, so it said "Saved." and then
    showed "CLI default" again.

    `app/prefs.py` derives its keys from the harness roster for exactly this
    reason — the stale copy simply lived one layer up, which is the failure
    mode `CLAUDE.md`'s scalability rule is about. Accepting extras and
    filtering to `prefs.KEYS` in the handler keeps the vocabulary just as
    closed as spelling it out did (`prefs.write` filters to the same set), and
    a harness added to the roster is storable the moment it exists.
    """

    model_config = ConfigDict(extra="allow")


@router.get("/prefs")
def read_prefs(conn=Depends(get_app_state)) -> dict:
    return prefs.choices(conn)


@router.put("/prefs")
def write_prefs(body: PrefsWrite, conn=Depends(get_app_state)) -> dict:
    """Store what the reader chose, and answer with what is now stored.

    The filter to `prefs.KEYS` is what keeps the key space closed now that the
    schema accepts extras — a browser on localhost still cannot write a row
    this installation does not define. The length bound moves here with it,
    since there is no per-field `max_length` left to carry it.
    """
    written = {key: str(value)[:VALUE_MAX]
               for key, value in body.model_dump().items()
               if value is not None and key in prefs.KEYS}
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
