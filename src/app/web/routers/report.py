"""Compose a problem report or a suggestion. The reader sends it; this sends nothing.

Built from the same redacted log rows as the log section, so it is refused on
the extension's port and origins for the same reason (`logs.log_caller`).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import report
from app.web import state
from app.web.deps import get_app_state
from app.web.routers.logs import log_caller

router = APIRouter(prefix="/api/report", tags=["report"], dependencies=[Depends(log_caller)])


class Ask(BaseModel):
    kind: Literal["error", "suggestion"]
    job_id: str = Field("", max_length=64)
    note: str = Field("", max_length=report.NOTE_CHARS)


@router.post("/draft")
def draft(ask: Ask, request: Request, conn=Depends(get_app_state)):
    """`{title, text, filename, url}`: the full text to copy and a prefilled issue link."""
    if ask.job_id and state.get_job(conn, ask.job_id) is None:
        raise HTTPException(404, f"no such job: {ask.job_id}")
    return report.draft(conn, kind=ask.kind, job_id=ask.job_id, note=ask.note,
                        issues_url=request.app.state.settings.issues_url)
