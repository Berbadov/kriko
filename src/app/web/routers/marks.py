"""What the reader thought of a claim.

Kriko has no authority to promote or retract a claim — that is the whole
premise of the trust model, and it is why a pack ships evidence rather than
verdicts. So a reader who spots a claim that is wrong about their own car has,
until now, had nowhere to put that. The answer they get from a mechanic is the
best signal this project could possibly receive, and it was being thrown away.

A mark is not evidence and does not pretend to be. It goes in `app.sqlite`
beside the reader's history, never in the engine's store: an opinion must not
change a pack's `content_digest`, and uninstalling a pack must not erase what
the reader said about it. Nothing in `kriko/` reads this table, and ranking is
untouched — a marked-wrong claim still surfaces, because one reader's car is
not a refutation.

What it is *for* is the loop that follows: the marks are a queue of claims
worth re-researching, in the reader's own words, and `wrong` versus
`not_applicable` is the difference between a knowledge problem and a matching
problem. That distinction is the one thing an automated pass cannot infer from
the claim row alone.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/marks", tags=["marks"])


class MarkRequest(BaseModel):
    pack_id: str = Field(min_length=1, max_length=200)
    claim_id: str = Field(min_length=1, max_length=200)
    verdict: str
    # Free text, and the most valuable field here: "my mechanic says the belt
    # was done at 90k" is the sentence a later research pass wants.
    note: str = Field(default="", max_length=2000)
    # Snapshots, so a mark stays readable after the pack that carried the
    # claim is updated or removed. See `claim_marks` in `state.py`.
    subject_id: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=500)


@router.get("")
def list_marks(
    verdict: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    conn=Depends(get_app_state),
) -> dict:
    """Every mark plus the counts, in one request.

    Together because a list of marks with no denominator says nothing: "four
    claims marked wrong" matters differently at four marks and at four hundred.
    """
    if verdict is not None and verdict not in state.VERDICTS:
        raise HTTPException(422, f"unknown verdict: {verdict}")
    return {
        "items": state.marks(conn, verdict=verdict, limit=limit),
        "counts": state.mark_counts(conn),
        "verdicts": list(state.VERDICTS),
    }


@router.get("/signals")
def signals(
    limit: int = Query(50, ge=1, le=200), conn=Depends(get_app_state)
) -> dict:
    """What the marks add up to, split by which system has the problem.

    The queue, not the marks: `wrong` groups into subjects worth re-researching
    and `not_applicable` into subjects whose *matching* is wrong, with the
    doors they arrived through attached. Declared before `""`'s siblings by
    path, and above `POST` here only for reading order.

    Not a review screen. The research queue is the input to the research job
    this app already runs — see the automation principle: a mark that needs a
    person to triage it is the same dead end it was before.
    """
    return state.mark_signals(conn, limit)


@router.post("")
def mark(body: MarkRequest, conn=Depends(get_app_state)) -> dict:
    try:
        return state.mark_claim(
            conn,
            pack_id=body.pack_id,
            claim_id=body.claim_id,
            verdict=body.verdict,
            note=body.note,
            subject_id=body.subject_id,
            title=body.title,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.delete("/{pack_id}/{claim_id}")
def unmark(pack_id: str, claim_id: str, conn=Depends(get_app_state)) -> dict:
    """Taking it back. Not a 404 when there was nothing there: pressing the
    same button twice is how a reader toggles, and the end state is what they
    asked for either way."""
    return {"removed": state.unmark_claim(conn, pack_id, claim_id)}
