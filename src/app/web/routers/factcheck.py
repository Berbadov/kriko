"""One press: does the page this claim cites still say it?

`app/factcheck.py` holds the reasoning about what this check is and — more
importantly — what it is not. This router is the thin part: read the claim's
evidence out of the engine's store, re-read the pages, record the answer in
the interface's own file.

Two shapes on purpose. The POST is a *request* rather than a job because the
reader is standing there having just pressed a button, and the work is at most
three HTTP GETs with an eight-second ceiling each. The GET is the accumulated
answer for a whole screen, so a result page can show what is already known
about forty claims without forty requests — and without re-fetching anything.

The quote is never taken from the caller. The extension and the app both send
nothing but an address (`pack_id` + `claim_id`), and the text checked is the
one the installed pack shipped: a check whose input came from the page being
checked would prove nothing at all.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import factcheck
from app.web import state
from app.web.deps import get_app_state, get_store
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/factcheck", tags=["factcheck"])

#: The whole-screen verb lives at `/api/verify`, not under
#: `/api/factcheck`: one claim is a fact check, and "verify the
#: knowledge here" is an *operation* with a job behind it. Two nouns
#: would have been one endpoint doing two jobs.
verify_router = APIRouter(prefix="/api", tags=["verify"])


class CheckRequest(BaseModel):
    pack_id: str = Field(min_length=1, max_length=200)
    claim_id: str = Field(min_length=1, max_length=200)


@router.get("")
def list_checks(
    verdict: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    conn=Depends(get_app_state),
) -> dict:
    if verdict is not None and verdict not in factcheck.VERDICTS:
        raise HTTPException(422, f"unknown verdict: {verdict}")
    return {
        "items": state.fact_checks(conn, verdict=verdict, limit=limit),
        "counts": state.fact_check_counts(conn),
    }


@router.post("")
def check(
    body: CheckRequest,
    store=Depends(get_store),
    conn=Depends(get_app_state),
) -> dict:
    """Re-read the sources behind one claim, and record what they say now."""
    claim = store.execute(
        "SELECT c.subject_id, COALESCE(t.title, '') AS title"
        " FROM claims c"
        " LEFT JOIN claim_text t"
        "   ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id"
        " WHERE c.claim_id = ? AND c.pack_id = ?",
        (body.claim_id, body.pack_id),
    ).fetchone()
    if claim is None:
        # A claim this store does not carry is a stale link, not a server
        # fault: a pack was updated or removed under a page left open.
        raise HTTPException(404, f"no claim {body.claim_id} in pack {body.pack_id}")

    sources = [
        {"url": row["url"], "quote": row["quote"]}
        for row in store.execute(
            "SELECT s.url, e.quote FROM evidence e"
            " JOIN sources s USING (source_id, pack_id)"
            " WHERE e.claim_id = ? AND e.pack_id = ?"
            # Supporting evidence first: a claim's own source is what a
            # re-check is about, and a rebuttal quote going missing is a
            # different question than the one being asked.
            " ORDER BY CASE e.stance WHEN 'supports' THEN 0 ELSE 1 END",
            (body.claim_id, body.pack_id),
        )
    ]

    result = factcheck.check_claim(sources)
    return state.record_fact_check(
        conn,
        pack_id=body.pack_id,
        claim_id=body.claim_id,
        verdict=result["verdict"],
        detail=result["detail"],
        sources=result["sources"],
        subject_id=claim["subject_id"],
        title=claim["title"],
    )


class VerifyRequest(BaseModel):
    """Everything on this screen, re-read. B128.

    One claim is the POST above — a request, because the reader is standing
    there. A pack is a *job*: forty claims at three fetches each with an
    eight-second ceiling is minutes, and minutes belong in a row that outlives
    the request.
    """

    pack_id: str = Field("", max_length=200)
    subject_id: str = Field("", max_length=200)
    limit: int = Field(50, ge=1, le=500)


@verify_router.post("/verify")
def verify(body: VerifyRequest, request: Request) -> dict:
    """Verify the knowledge here — as an operation rather than a press.

    No model and no agent: the question is "does the quote still appear on the
    page", which a substring test answers honestly and an LLM would answer
    confidently. Free, so it needs no budget; reporting, so it retracts
    nothing.
    """
    runner = request.app.state.jobs
    return {
        "job_id": runner.submit("verify", body.model_dump()),
        "kind": "verify",
    }
