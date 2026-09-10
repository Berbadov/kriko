"""The unattended run, and the way back out of one.

Four surfaces, and the third is the reason the first two are allowed to exist:

* `GET /api/research-planes` says which planes exist and what each one costs.
* `POST /api/agenda/run` walks the agenda without being told what to research.
* `GET /api/research-runs` says what each run cost and what it added.
* `GET /api/usage` adds the sums up, which no per-run row can answer.
* `GET|PUT /api/schedule` is the unattended loop, off until it is turned on.
* `DELETE /api/research-runs/{id}` takes a run's claims back out.

The order matters. An unattended multi-row run that could not be reversed would
be a liability rather than a feature — a reader who lets it loose and dislikes
the result has to trust the claims or hand-delete them one by one — so the undo
landed before the loop that needs it, and both live here rather than in
`routers/jobs.py` because they are one story.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import keys
from app.web import observability, schedule, state
from app.web.deps import get_app_state, get_jobs

router = APIRouter(prefix="/api", tags=["research"])


#: What each plane is for, in the reader's terms. The engine's `cost_basis`
#: is accurate and says nothing — "per_token" is not an answer to "what will
#: this cost me" — so the sentence lives here, where the interface's words
#: belong, beside the machine-readable value rather than instead of it.
PLANE_WORDS = {
    "harness": (
        "Kriko runs your coding agent for you, headlessly, and files what it "
        "finds. Costs nothing beyond the subscription you already pay for, "
        "and needs the agent's command-line tool installed."
    ),
    "agent": (
        "You do the run yourself: Kriko writes the brief, your agent reads it "
        "through the MCP server and files the findings back. Costs nothing "
        "beyond your subscription, and needs a harness connected on the "
        "Wiring tab."
    ),
    "api": (
        "Kriko searches and reads by itself, unattended. Costs money per run, "
        "capped by a budget you set, and needs both keys below."
    ),
}


@router.get("/research-planes")
def list_planes() -> dict:
    """The two ways knowledge gets built, and whether each one can run now.

    Read off the researcher classes rather than restated in the frontend, for
    the same reason `/api/pipeline/runs` hands over its stage labels: a second
    copy of a vocabulary is a second place to forget when it changes. What the
    interface adds is the sentence and the readiness — `cost_basis` is the
    engine's word and the reader's question is "can I press this".

    Returns no key and no hint. `/api/keys` is the only surface that describes
    what is stored, and even that one returns only a masked tail.
    """
    from app.providers import harness as harness_mod
    from app.providers.harness import HarnessResearcher
    from kriko.research import AgentResearcher, ApiResearcher

    ready = keys.ready()
    installed = harness_mod.available()
    planes = []
    for cls in (HarnessResearcher, AgentResearcher, ApiResearcher):
        row = {
            "id": cls.name,
            "cost_basis": cls.cost_basis,
            "what": PLANE_WORDS.get(cls.name, ""),
            # The `agent` plane's readiness is a *harness config* question,
            # which `/api/agent-targets` already answers and this must not
            # second-guess. The other two have a prerequisite this router can
            # see: a key, or an executable on PATH.
            "ready": True,
            "needs_keys": cls.name == "api",
        }
        if cls.name == "api":
            row["ready"] = ready
        if cls.name == "harness":
            row["ready"] = bool(installed)
            # Named, not counted. "no coding-agent CLI found" is answerable
            # only if the reader knows which names were looked for.
            row["harnesses"] = [
                {"id": h.id, "label": h.label, "command": h.executable}
                for h in installed
            ]
            row["looked_for"] = [h.executable for h in harness_mod.KNOWN]
        planes.append(row)
    return {"planes": planes}


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


class ScheduleRequest(BaseModel):
    """The unattended loop, as the reader sets it.

    Every field optional: the screen saves the one control the reader touched,
    and a PUT that had to carry all six would make a partial save silently
    reset the rest.
    """

    enabled: bool | None = None
    every_hours: float | None = Field(None, ge=schedule.MIN_HOURS, le=24 * 30)
    rows: int | None = Field(None, ge=1, le=100)
    #: Not validated against a list here — `schedule.decide` refuses an
    #: unknown plane by name, and one place to refuse is better than two that
    #: can disagree.
    plane: str | None = None
    budget_usd: float | None = Field(None, ge=0.0, le=100.0)
    max_documents: int | None = Field(None, ge=1, le=50)


@router.get("/schedule")
def read_schedule(app_state=Depends(get_app_state)) -> dict:
    """What the loop is set to, and what it last did.

    The history is returned even when the loop is off, because "it ran four
    times and the last one kept nothing" is precisely what a reader wants to
    see *after* switching it off.
    """
    return schedule.status(app_state)


@router.put("/schedule")
def write_schedule(
    body: ScheduleRequest, request: Request, app_state=Depends(get_app_state)
) -> dict:
    """Save it, and start or stop the thread to match.

    Applied to the running process rather than only stored, because a setting
    that needs a restart to take effect is a setting a reader will conclude is
    broken. Turning it off stops the thread; turning it on starts one, and
    the first tick still waits out the startup grace.
    """
    stored = {
        key: value
        for key, value in body.model_dump().items()
        if value is not None
    }
    merged = {**schedule.settings_for(app_state), **stored}
    state.put_settings(app_state, {schedule.KEY: merged})

    loop = getattr(request.app.state, "schedule", None)
    if loop is not None:
        if schedule.settings_for(app_state)["enabled"]:
            loop.start()
        else:
            loop.stop()
    return schedule.status(app_state)


@router.post("/schedule/check")
def check_schedule(request: Request, app_state=Depends(get_app_state)) -> dict:
    """Run one tick now, and say what it decided.

    The manual half of an automatic feature, and the reason it exists is
    trust: a reader who turns on a loop that will next act in twenty-four
    hours has no way to find out whether it *would* act. This returns the same
    sentence the loop would have recorded — including the refusals, which are
    the answers worth having.
    """
    loop = getattr(request.app.state, "schedule", None)
    if loop is None:
        raise HTTPException(503, "this process has no scheduler")
    decision = loop.tick(from_timer=False)
    return {
        "ran": decision.run,
        "reason": decision.reason,
        "due_at": decision.due_at,
        **schedule.status(app_state),
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


@router.get("/usage")
def read_usage(request: Request, app_state=Depends(get_app_state)) -> dict:
    """Everything this installation has spent, and everything it was asked.

    Two halves, because a reader asking "what has this cost me" is asking
    about both and neither half can answer alone. `research` sums the runs
    that wrote claims *in*; `analyses` counts the lookups that read them back
    *out*, off the JSONL log whose contents nothing reachable has ever read.
    Together they are the only place the ratio is visible: a hundred analyses
    served by four runs is a very different installation from four analyses
    served by a hundred.

    Nothing here is computed from a guess. A plane that cannot count leaves
    its column null all the way to the wire, and `metered_runs` says how many
    of the runs behind a total were counted at all — see
    `state.usage_totals`.
    """
    return {
        "research": state.usage_totals(app_state),
        "analyses": observability.summarise(
            request.app.state.settings.analysis_log_path
        ),
    }


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
