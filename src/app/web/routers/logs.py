"""The log section: every job's steps in order, with timing, filters and an export (#261).

Reads the `job_steps` rows that `state.update_job` and `Progress.watch` write
(`app/web/steps.py` says how); owns no logic of its own. A request names a job,
a level, a source or a word, and gets rows back; one row expands to the exact
request and reply, redacted; the export is the same rows as plain text.

**Not reachable from a browser extension.** The rows hold prompts and replies
(after redaction), which the per-job `/api/jobs/{id}/log` summary does not. Any
extension the reader has installed may call the rest of this API, so this
router refuses the extension's port and its origins, exactly as the terminal
does (`origins.terminal_origin_is_allowed`): the desktop window is the only
reader of its own log.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.web import origins, state, steps
from app.web.deps import get_app_state
from app.web.settings import EXTENSION_PORT

logger = logging.getLogger(__name__)


def log_caller(request: Request) -> None:
    server = request.scope.get("server")
    if server is not None and server[1] == EXTENSION_PORT:
        raise HTTPException(403, "The log cannot be read on the extension port.")
    origin = request.headers.get("origin")
    if not origins.terminal_origin_is_allowed(origin):
        logger.warning("log refused: origin %r not allowed", origin)
        raise HTTPException(403, f"Origin {origin!r} is not allowed to read the log.")


router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(log_caller)])


@router.get("/jobs")
def log_jobs(
    limit: int = Query(60, ge=1, le=200),
    kind: str = Query("", max_length=200),
    state_: str = Query("", alias="state", max_length=200),
    q: str = Query("", max_length=200),
    conn=Depends(get_app_state),
):
    """Jobs, newest first, each with what its log holds: steps, errors, calls, tokens, cost."""
    return {"items": steps.list_jobs(conn, limit=limit, kind=kind, state=state_, q=q),
            "levels": list(steps.LEVELS), "sources": list(steps.SOURCES)}


@router.get("/steps")
def log_steps(
    job_id: str = Query("", max_length=64),
    level: str = Query("", max_length=64),
    source: str = Query("", max_length=128),
    q: str = Query("", max_length=200),
    limit: int = Query(1000, ge=1, le=5000),
    after_id: int = Query(0, ge=0),
    conn=Depends(get_app_state),
):
    """Steps oldest first. `level` and `source` take a comma-separated list."""
    return steps.list_steps(conn, job_id=job_id, level=level, source=source, q=q,
                            limit=limit, after_id=after_id)


@router.get("/steps/{step_id}")
def log_step(step_id: int, conn=Depends(get_app_state)):
    """One step with its exact request and reply, redacted."""
    found = steps.step_detail(conn, step_id)
    if found is None:
        raise HTTPException(404, f"no such step: {step_id}")
    return found


@router.get("/export")
def log_export(
    job_id: str = Query("", max_length=64),
    level: str = Query("", max_length=64),
    source: str = Query("", max_length=128),
    q: str = Query("", max_length=200),
    bodies: bool = Query(False),
    conn=Depends(get_app_state),
):
    """The same rows as plain text: `{filename, text}`. `bodies` adds each prompt and reply."""
    if job_id and state.get_job(conn, job_id) is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return steps.export_text(conn, job_id=job_id, level=level, source=source, q=q,
                             bodies=bodies)
