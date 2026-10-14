"""Bounded, durable inspection of research execution and its attempt history."""

import asyncio
import json
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.web import state
from app.web.deps import get_app_state, get_jobs


router = APIRouter(prefix="/api", tags=["jobs"])


def _manifest(runner, job_id: str) -> dict:
    saved = runner.ledger.lookup_job(job_id)
    if saved is None:
        raise HTTPException(404, "this job has no agent manifest")
    return saved


@router.get("/jobs/{job_id}/manifest")
def manifest(job_id: str, runner=Depends(get_jobs)) -> dict:
    saved = _manifest(runner, job_id)
    # A manifest is an index into saved evidence, not another copy of the
    # product listing, final answer, or assembled prompt.
    kept = {key: value for key, value in saved.items() if key not in {"input", "result"}}
    kept["snapshot"] = dict(kept.get("snapshot") or {})
    kept["snapshot"]["settings"] = {key: value for key, value in
        (kept["snapshot"].get("settings") or {}).items()
        if key not in {"store_path", "packs_dir", "app_state_path"}}
    kept["attempts"] = [{key: value for key, value in attempt.items()
                         if key not in {"request", "detail", "error"}}
                        for attempt in runner.ledger.attempts(saved["run_id"], limit=50)]
    return kept


@router.get("/jobs/{job_id}/log")
def log(job_id: str, cursor: int = Query(0, ge=0),
        limit: int = Query(6000, ge=1, le=16000),
        tail: bool = False, q: str = Query("", max_length=200),
        conn=Depends(get_app_state)) -> dict:
    row = conn.execute("SELECT LENGTH(log), state FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such job")
    total, outcome = row
    start = max(0, total - limit) if tail else min(cursor, total)
    if q:
        found = conn.execute("SELECT INSTR(SUBSTR(log, ?), ?) FROM jobs WHERE job_id=?",
                             (start + 1, q, job_id)).fetchone()[0]
        start = start + found - 1 if found else total
    text = conn.execute("SELECT SUBSTR(log, ?, ?) FROM jobs WHERE job_id=?",
                        (start + 1, limit, job_id)).fetchone()[0]
    return {"text": text, "cursor": start, "next_cursor": start + len(text),
            "total_chars": total, "cursor_units": "characters",
            "eof": start + len(text) >= total, "done": outcome in state.TERMINAL}


@router.get("/jobs/{job_id}/events")
async def events(job_id: str, request: Request, cursor: int = Query(0, ge=0),
                 last_event_id: str | None = Header(default=None),
                 runner=Depends(get_jobs)):
    saved = await run_in_threadpool(_manifest, runner, job_id)
    if last_event_id is not None:
        try:
            supplied = int(last_event_id)
        except ValueError as error:
            raise HTTPException(422, "Last-Event-ID must be a nonnegative event cursor") from error
        if supplied < 0:
            raise HTTPException(422, "Last-Event-ID must be nonnegative")
        cursor = max(cursor, supplied)
    run_id = saved["run_id"]

    async def stream():
        position = cursor
        ticks = 0
        yield "event: snapshot\ndata: " + json.dumps({
            "job_id": job_id, "run_id": run_id, "state": saved["state"],
            "input_hash": saved["input_hash"],
        }) + "\n\n"
        while not await request.is_disconnected():
            try:
                batch = await run_in_threadpool(runner.ledger.logs, run_id, cursor=position, limit=50)
                current = await run_in_threadpool(_status, runner.ledger, run_id)
            except (sqlite3.Error, ValueError, OSError):
                yield 'event: error\ndata: {"message":"could not read persisted run state"}\n\n'
                return
            for event in batch["events"]:
                position = event["seq"]
                public = {key: value for key, value in event.items() if key != "data"}
                public["data"] = {key: value for key, value in event.get("data", {}).items()
                                  if key not in {"detail", "error", "request"}}
                yield f"id: {position}\nevent: {event['event']}\ndata: {json.dumps(public)}\n\n"
            if current is None:
                yield 'event: error\ndata: {"message":"run disappeared"}\n\n'
                return
            if current["terminal_at"] and len(batch["events"]) < 50:
                yield "event: complete\ndata: " + json.dumps({"state": current["state"],
                    "result_digest": current["result_digest"]}) + "\n\n"
                return
            ticks += 1
            if ticks % 40 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _status(ledger, run_id: str) -> dict | None:
    conn = ledger.connect()
    try:
        row = conn.execute("SELECT state, terminal_at, result_digest FROM agent_runs WHERE run_id=?",
                           (run_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()
