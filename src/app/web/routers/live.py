"""Answers that follow the knowledge (B152.4).

"A card added by the agent, we instantly see the new card." Two pieces:

- `GET /api/knowledge/clock` — one value that moves whenever anything writes
  to the knowledge store, from any process (`app/web/knowledge_clock.py`).
  Cheap enough to ask every second or two.
- `POST /api/lookup/{id}/refresh` — the saved question asked again of the
  knowledge as it is now, written over the saved answer. Same id, same place
  in history: a re-answer is not a new lookup, so it records no operation, no
  analysis-log line and no history row.

A client holding an answer watches the clock and, when it moves, refreshes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from app.web import state
from app.web.deps import get_app_state, get_store
from app.web.routers import analyze, query

router = APIRouter(prefix="/api", tags=["live"])


def clock_of(request: Request) -> str:
    return request.app.state.knowledge_clock.now()


@router.get("/knowledge/clock")
def knowledge_clock(request: Request) -> dict:
    return {"clock": clock_of(request)}


@router.post("/lookup/{lookup_id}/refresh")
def refresh_lookup(
    lookup_id: str,
    request: Request,
    store=Depends(get_store),
    app_state=Depends(get_app_state),
) -> dict:
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, f"no such lookup: {lookup_id}")
    saved = row["request"] or {}
    try:
        if row["source"] == "ask":
            payload, _ = query.answer(store, query.LookupRequest(**saved))
        elif row["source"] in ("analyze", "extension"):
            body = analyze.ScrapeRequest(**saved)
            payload, mapped, _ = analyze.answer(store, app_state, body)
            if mapped is None:
                # The page read before and cannot now (a pack was removed):
                # the saved answer stays what it was rather than becoming a
                # refusal the reader did not ask for.
                return {**row, "refreshed": False, "clock": clock_of(request)}
        else:
            return {**row, "refreshed": False, "clock": clock_of(request)}
    except ValidationError:
        # A row written by an older app whose request no longer fits the
        # model: keep the answer it has.
        return {**row, "refreshed": False, "clock": clock_of(request)}
    payload["lookup_id"] = lookup_id
    state.replace_response(app_state, lookup_id, payload)
    if row["source"] != "ask":
        payload["url"] = saved.get("url", "")
        payload["compare_ready"] = state.lookup_count(app_state) >= 2
    return {**row, "response": payload, "refreshed": True, "clock": clock_of(request)}
