"""Follow-up questions about a shortlist, asked of the reader's own agent.

The Compare screen lines up checks the reader already has; what it never let
them do is ask the question the table raises — "which of these has the
cheaper known fix" — anywhere but in their head. A question is a job rather
than a request because it runs an agent that may search for a few minutes,
and because the answer is worth outliving the page: it is stored beside the
comparison it was about, so reopening the draft reopens the conversation.

The brief is assembled from the stored answers themselves, never from the
engine: each check's own claims and specifications are passed through
verbatim, so a question about any category works without this layer knowing
any category (G6). Nothing the agent replies is filed as knowledge — this is
the reader's own decision support, not a submission path, and it writes only
to `app.sqlite`.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/compare-drafts", tags=["compare"])


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    harness: str = Field(default="", max_length=200)


@router.get("/{draft_id}/questions")
def list_questions(draft_id: str, conn=Depends(get_app_state)) -> dict:
    return {"items": state.compare_questions(conn, draft_id)}


@router.post("/{draft_id}/questions")
def ask_question(
    draft_id: str, body: QuestionRequest,
    request: Request, conn=Depends(get_app_state),
) -> dict:
    """Store the question, then start the job that answers it.

    The row is written before the job is submitted, so a question asked the
    moment before a crash is a row that says "asked", not a question that
    never existed. The job's params carry the question id; its handler writes
    the answer back onto that row when the agent replies.
    """
    if not state.get_compare_draft(conn, draft_id):
        raise HTTPException(404, f"no draft {draft_id}")
    try:
        question = state.record_compare_question(
            conn, draft_id, body.question.strip())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    runner = request.app.state.jobs
    try:
        job_id = runner.submit("compare_ask", {
            "draft_id": draft_id,
            "question_id": question["question_id"],
            "question": question["question"],
            "harness": body.harness,
        })
    except KeyError as exc:  # pragma: no cover - the handler is registered
        raise HTTPException(400, str(exc)) from exc
    return {**question, "job_id": job_id, "kind": "compare_ask"}
