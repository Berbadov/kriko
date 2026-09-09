"""The unattended run, and the way back out of one.

Three surfaces, and the third is the reason the other two are allowed to exist:

* `POST /api/agenda/run` walks the agenda without being told what to research.
* `GET /api/research-runs` says what each run cost and what it added.
* `DELETE /api/research-runs/{id}` takes a run's claims back out.

The order matters. An unattended multi-row run that could not be reversed would
be a liability rather than a feature — a reader who lets it loose and dislikes
the result has to trust the claims or hand-delete them one by one — so the undo
landed before the loop that needs it, and both live here rather than in
`routers/jobs.py` because they are one story.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state, get_jobs

router = APIRouter(prefix="/api", tags=["research"])


class AgendaRunRequest(BaseModel):
    #: How far down the agenda to go. Small by default: this is the button
    #: pressed by somebody who is not watching.
    rows: int = Field(10, ge=1, le=100)
    pack_id: str | None = None
    #: `agent` again, and for the third time in this codebase deliberately: the
    #: unattended door is the *last* place a default should start spending.
    backend: str = "agent"
    #: The ceiling for the whole run, not per row. Zero on the `api` plane is
    #: replaced by `tasks.DEFAULT_AGENDA_BUDGET_USD` rather than meaning
    #: unlimited — see the note there.
    budget_usd: float = Field(0.0, ge=0.0, le=100.0)
    max_documents: int = Field(5, ge=1, le=50)


@router.post("/agenda/run")
def start_agenda_run(body: AgendaRunRequest, runner=Depends(get_jobs)) -> dict:
    return {
        "job_id": runner.submit("agenda_run", body.model_dump()),
        "kind": "agenda_run",
    }


@router.get("/research-runs")
def list_runs(
    limit: int = Query(50, ge=1, le=200), app_state=Depends(get_app_state)
) -> dict:
    """Provenance, newest first: plane, model, provider, spend, claims still in.

    `claims` is counted rather than stored, so a run that has been undone reads
    as zero here instead of still advertising what it once added.
    """
    return {"runs": state.research_runs(app_state, limit)}


@router.get("/research-runs/{run_id}")
def read_run(run_id: str, app_state=Depends(get_app_state)) -> dict:
    run = state.get_research_run(app_state, run_id)
    if run is None:
        raise HTTPException(404, f"no research run {run_id}")
    claims = state.run_claims(app_state, run_id)
    return {
        **run,
        "claims_detail": claims,
        # The one thing a screen must not do is offer an undo that would do
        # nothing. A run whose claims are all gone says so instead.
        "undoable": any(not item["removed_at"] for item in claims),
    }


@router.delete("/research-runs/{run_id}")
def undo_run(run_id: str, app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    """Start the undo. A job, because it writes once per claim.

    Refused up front for a run that does not exist — a 404 is the honest
    answer, and queuing a job that will immediately fail would report the
    mistake as a failed run instead of as a bad request.
    """
    if state.get_research_run(app_state, run_id) is None:
        raise HTTPException(404, f"no research run {run_id}")
    return {
        "job_id": runner.submit("research_undo", {"run_id": run_id}),
        "kind": "research_undo",
    }
