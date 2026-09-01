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
    #: `agent` is the $0 plane and stays the default here for the same reason
    #: it is the default in `kriko.research.get_researcher`: a button that
    #: quietly starts spending money is a button people stop pressing.
    backend: str = "agent"
    budget_usd: float = 0.0
    max_documents: int = Field(5, ge=1, le=50)


class UpdateRequest(BaseModel):
    #: Empty means "everything the index has something newer for". Naming one
    #: pack is the exception, not the shape of the operation.
    pack_id: str | None = None
    index_url: str | None = None


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


@router.get("/jobs/{job_id}")
def get_job(job_id: str, app_state=Depends(get_app_state)):
    row = state.get_job(app_state, job_id)
    if row is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return row


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, runner=Depends(get_jobs)):
    outcome = runner.cancel(job_id)
    if outcome is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return {"job_id": job_id, "state": outcome}


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
