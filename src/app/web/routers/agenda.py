"""What to research next — the same rows the MCP tool hands an agent.

`app/agenda.py` holds the reasoning: four signals kept separate, computed on
read, and one row kind (`unknown_subject`) that is a message to the catalog
rather than a task for an agent.

This surface exists so the reader can see the ordering *before* an agent acts
on it, and so a harness that is not wired to the MCP server at all can still be
handed a row as a prompt. A GET, with no job behind it: the computation is four
indexed queries and the tail of a log, and a screen that had to wait on a
worker to find out what to research would be a screen nobody opens.
"""

from fastapi import APIRouter, Depends, Query, Request

from app import agenda
from app.web.deps import get_app_state, get_store

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


@router.get("")
def read_agenda(
    request: Request,
    pack_id: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=200),
    store=Depends(get_store),
    app_state=Depends(get_app_state),
) -> dict:
    return agenda.compute(
        store,
        app_state=app_state,
        log_path=request.app.state.settings.analysis_log_path,
        pack_id=pack_id,
        limit=limit,
    )
