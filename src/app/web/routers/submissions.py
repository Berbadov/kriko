"""What researchers submitted, and what the gate did with it.

`app/findings.py` refuses most of what arrives, for reasons that name the rule
it broke — a quote that is not in the document, a title tied to nothing
specific, an item the pack's own gate calls routine. Those sentences are the
best feedback loop this project has for the agent skill, and before this router
they existed only in a function's return value.

Reads `app.sqlite` and nothing else. A refusal is not pack content: it must not
touch a `content_digest`, and it must survive uninstalling the pack whose gate
produced it.
"""

from fastapi import APIRouter, Depends, Query

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api", tags=["submissions"])


@router.get("/submissions")
def list_submissions(
    limit: int = Query(30, ge=1, le=200),
    conn=Depends(get_app_state),
) -> dict:
    """The recent batches, plus why findings are being refused overall.

    One request, because a list of batches without the reason histogram is a
    log, and the histogram is the part that tells an author what to change.
    """
    items = state.submissions(conn, limit)
    return {
        "items": items,
        "accepted": sum(item["accepted"] for item in items),
        "refused": sum(item["refused"] for item in items),
        "reasons": state.refusal_reasons(conn),
    }
