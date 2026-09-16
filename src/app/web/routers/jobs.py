"""Starting, watching and stopping the two operations that grow a pack.

The router owns no logic — the handlers are in `app/web/tasks.py` and the state
machine is in `app/web/state.py`. What it owns is the promise G6's delivery
constraint makes: a durable id comes back immediately, the status is readable
afterwards even across a restart, and a failure arrives as a message rather
than as silence.

`/stream` is Server-Sent Events over a poll of the row, not a push from the
worker. A queue would have to be wired through the thread pool and would still
lose everything on reconnect; polling the row means a browser that reconnects
mid-job sees the truth, and that the row stays the single source of it.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.web import state, tasks
from app.web.deps import get_app_state, get_jobs

router = APIRouter(prefix="/api", tags=["jobs"])

#: How often `/stream` re-reads the row. Fast enough to feel live, slow enough
#: that a job logging in a tight loop is not also a busy loop here.
POLL_SECONDS = 0.5


class ResearchRequest(BaseModel):
    subject_id: str
    pack_id: str | None = None
    #: Empty means `tasks.default_backend()`: the best plane that is free
    #: *and* can actually gather. It was `agent`, which gathers nothing by
    #: design, so on a machine with a coding-agent CLI installed the Research
    #: button rendered a brief and reported success — the reader's "run
    #: nothing again". Resolved at run time, because whether a CLI is
    #: installed is a fact about the machine, not about this schema.
    #:
    #: The rule that survives unchanged: a button that quietly starts
    #: *spending money* is a button people stop pressing. `api` is still
    #: never chosen by omission.
    backend: str = ""
    budget_usd: float = 0.0
    #: `0` means "whatever the scale says", and that is why the default is not
    #: 5 any more. A truthy default silently won over every preset, so the dial
    #: would have moved the label and nothing else — the exact bug where a
    #: control appears to work and does not.
    max_documents: int = Field(0, ge=0, le=50)
    #: How deep to go: `quick` | `standard` | `deep` | `custom`.
    #:
    #: One name instead of four numbers, and the numbers still work — an
    #: explicit `max_documents` or `budget_usd` wins over whatever the preset
    #: proposes, because the dial is a bundle of these knobs rather than a wall
    #: around them. Empty means the default, and an unknown name means the
    #: default too: a request from an older client, or with a typo, should run
    #: rather than be refused.
    scale: str = Field("", max_length=32)


class UpdateRequest(BaseModel):
    #: Empty means "everything the index has something newer for". Naming one
    #: pack is the exception, not the shape of the operation.
    pack_id: str | None = None
    index_url: str | None = None


class AuthorRequest(BaseModel):
    """One field, on purpose. (D4)

    The screen this replaces asked for a directory, a pack id, a name and an
    identity table. Three of those four are things an agent that has read the
    category can decide better than a reader who has not, and the fourth — the
    directory — is derived from the pack id rather than accepted, because an
    agent that could name a directory would eventually name one `../../`.
    """
    category: str = Field(min_length=2, max_length=200)
    #: Which installed CLI, when there is more than one. Empty means the first
    #: one Kriko can both start and sandbox.
    harness: str = ""
    timeout_seconds: float = 0.0
    #: Answers to the questions a previous run asked, keyed by their id.
    #:
    #: Supplied at the *start* of a run rather than during one, and that is the
    #: whole design rather than a shortcut. The identification pass is
    #: non-blocking — it states its assumptions and carries on — so an answer
    #: arriving mid-run would have nothing left to change. What it does instead
    #: is make the next run exact, which is why the questions are written to
    #: the job row where a client can offer them back alongside "run it again".
    #: A run nobody answers is still a run; see `app/disambiguate.py`.
    answers: dict[str, str] = Field(default_factory=dict)


class BuildRequest(BaseModel):
    root: str
    out: str | None = None
    install: bool = True


def _submit(runner, kind: str, params: dict) -> dict:
    try:
        job_id = runner.submit(kind, params)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": job_id, "kind": kind}


@router.post("/research")
def start_research(body: ResearchRequest, runner=Depends(get_jobs)):
    return _submit(runner, "research", body.model_dump())


@router.post("/packs/author")
def start_author(body: AuthorRequest, runner=Depends(get_jobs)):
    """Have the reader's own coding agent write a whole pack. Installs nothing.

    A job rather than a request because it spawns an agent that will search the
    web for a few minutes, and because the reply is worth outliving the page:
    the log holds what the agent said even when what it said was not a pack.
    """
    return _submit(runner, "pack_author", body.model_dump())


@router.post("/packs/build")
def start_build(body: BuildRequest, runner=Depends(get_jobs)):
    return _submit(runner, "pack_build", body.model_dump())


@router.get("/packs/updates")
def check_pack_updates(
    index_url: str | None = Query(default=None),
    runner=Depends(get_jobs),
):
    """Is anything newer? Answered in the request — it is one small fetch."""
    return tasks.check_updates(runner.settings, index_url or "")


@router.post("/packs/update")
def start_update(body: UpdateRequest, runner=Depends(get_jobs)):
    return _submit(runner, "pack_update", body.model_dump())


@router.get("/jobs")
def list_jobs(
    limit: int = Query(30, ge=1, le=200),
    app_state=Depends(get_app_state),
):
    return {"items": state.list_jobs(app_state, limit)}


def _with_attention(row: dict) -> dict:
    """Mark a job that has put something to the reader.

    "If the agent is waiting on my answer, that must be unmissable." It is not
    *waiting* — the identification pass states its defaults and carries on, by
    design (`app/disambiguate.py`) — but it is the one thing on the screen
    worth looking at, and a question rendered as another log line is a question
    nobody answers.

    Derived here rather than stored, because the questions are already in the
    job's own partial result and a second copy is a second thing to keep in
    step. It survives the run finishing: the answers make the *next* run exact,
    so they are worth offering beside "run it again" long after this one ended.
    """
    result = row.get("result") or {}
    questions = result.get("questions") if isinstance(result, dict) else None
    row["attention"] = {
        "kind": "questions",
        "count": len(questions),
        "say": (
            f"{len(questions)} question(s) about what this is — it carried on "
            f"with its own answers. Yours would make the next run exact."
        ),
        "questions": questions,
    } if isinstance(questions, list) and questions else None
    return row


@router.get("/jobs/{job_id}")
def get_job(job_id: str, app_state=Depends(get_app_state)):
    row = state.get_job(app_state, job_id)
    if row is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return _with_attention(row)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, runner=Depends(get_jobs)):
    outcome = runner.cancel(job_id)
    if outcome is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return {"job_id": job_id, "state": outcome}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, app_state=Depends(get_app_state), runner=Depends(get_jobs)):
    """Run the same work again, as a new row.

    A new job rather than a reset of the old one: the failed attempt's log is
    the only record of *why* it failed, and reusing the row would delete the
    evidence at the exact moment someone is looking into it. The two are linked
    by `retry_of` in the new job's params, so the pair stays readable.

    Refused while the original is still going — "retry" on a running job means
    the reader wanted to cancel it, and quietly starting a second copy of a
    research run is how you get two writers on one subject.
    """
    row = state.get_job(app_state, job_id)
    if row is None:
        raise HTTPException(404, f"no such job: {job_id}")
    if not row["done"]:
        raise HTTPException(409, f"job {job_id} is still {row['state']}")
    params = dict(row["params"] or {})
    params["retry_of"] = job_id
    return _submit(runner, row["kind"], params)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request_jobs=Depends(get_jobs)):
    """Follow one job to its end.

    Opens its own connection rather than taking the request-scoped one: the
    generator outlives the dependency's scope, and a dependency-managed
    connection would be closed under it on the first yield.
    """
    settings = request_jobs.settings

    async def events():
        conn = state.connect(settings.app_state_path)
        try:
            row = state.get_job(conn, job_id)
            if row is None:
                yield f"event: error\ndata: {json.dumps({'error': 'no such job'})}\n\n"
                return
            last = None
            while True:
                row = state.get_job(conn, job_id)
                if row is None:  # forgotten mid-stream
                    return
                # Only send on change, so an idle job costs one comparison per
                # tick instead of a message the browser has to re-render.
                fingerprint = (row["state"], row["progress"], row["message"], len(row["log"]))
                if fingerprint != last:
                    last = fingerprint
                    yield f"data: {json.dumps(row)}\n\n"
                if row["done"]:
                    return
                await asyncio.sleep(POLL_SECONDS)
        finally:
            conn.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
