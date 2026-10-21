"""Which providers search the web, how each has been doing, and a way to try one.

`app/providers/websearch.py` holds the mechanism and this file is the door:
the screen reads one document (`GET`), and presses one button to run a single
query through one provider (`POST /test`). The first choice and the order of
fallbacks are saved through `PUT /api/prefs` with the other settings
(`search_provider`, `search_fallback`); nothing here writes them, so there is
one place a preference is stored and validated.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import operations
from app.providers import websearch
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/search-providers", tags=["search"])


class SearchTest(BaseModel):
    provider: str
    #: Optional. The default is a neutral sentence, so a reader who only wants
    #: to know "does this answer" types nothing.
    query: str = ""


@router.get("")
def read(conn=Depends(get_app_state)) -> dict:
    """Each provider (needs a key, has one, last success, recent miss rate) and the order."""
    return websearch.status(conn)


@router.post("/test")
def test(request: Request, body: SearchTest, conn=Depends(get_app_state)) -> dict:
    """One query through one provider alone, and what came back.

    A hosted provider answers at the reader's cost for the one query, which is
    why this is a press and never something the page does by itself.
    """
    provider = body.provider.strip().casefold()
    if provider not in websearch.KNOWN:
        raise HTTPException(404, f"unknown search provider {body.provider}")
    path = getattr(request.app.state.settings, "app_state_path")
    with operations.record(path, door="app", name="search_test", kind="read",
                           arguments={"provider": provider}) as outcome:
        result = websearch.probe(conn, path, provider, body.query)
        outcome["response"] = operations.summarise(
            {"ok": result["ok"], "results": len(result["results"]), "error": result["error"]})
        return result
