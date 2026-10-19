"""Chat with the reader's own agent, over what the app has generated.

A thread is a conversation the reader keeps in `app.sqlite`. A message is a
question as the reader wrote it; posting one stores it and starts a `chat_ask`
job, which runs the turn (`app/chat.py`) and writes the answer back as an agent
message. The screen follows the job for its live steps and reads the thread
when the job is done.

Nothing here reads the knowledge store: the sources do, and only when the agent
asks for them during a turn.
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import chatdata
from app.web import livefeed, state
from app.web.deps import get_app_state

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _active_chat_job(conn, thread_id: str) -> str:
    """Latest queued or running chat turn for one conversation, if any."""
    rows = conn.execute(
        "SELECT job_id, params_json FROM jobs WHERE kind = 'chat_ask'"
        " AND state IN (?, ?, ?) ORDER BY rowid DESC",
        (state.QUEUED, state.RUNNING, state.CANCELLING),
    ).fetchall()
    for row in rows:
        try:
            params = json.loads(row["params_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(params, dict) and params.get("thread_id") == thread_id:
            return str(row["job_id"])
    return ""


class ThreadRequest(BaseModel):
    title: str = Field(default="", max_length=200)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    harness: str = Field(default="", max_length=200)
    backend: Literal["harness", "local"] = "harness"


@router.get("/sources")
def sources() -> dict:
    """The names and meanings of the records the agent may ask for. No data."""
    return {"items": chatdata.describe_sources()}


@router.get("/threads")
def list_threads(q: str = "", conn=Depends(get_app_state)) -> dict:
    return {"items": state.chat_threads(conn, q)}


class ThreadPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None


@router.patch("/threads/{thread_id}")
def change_thread(thread_id: str, body: ThreadPatch, conn=Depends(get_app_state)) -> dict:
    """Rename a conversation, pin it, or both."""
    if state.get_chat_thread(conn, thread_id) is None:
        raise HTTPException(404, f"no conversation {thread_id}")
    if body.title is not None:
        try:
            state.rename_chat_thread(conn, thread_id, body.title)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    if body.pinned is not None:
        state.pin_chat_thread(conn, thread_id, body.pinned)
    return state.get_chat_thread(conn, thread_id) or {}


@router.post("/threads")
def create_thread(body: ThreadRequest, conn=Depends(get_app_state)) -> dict:
    return state.create_chat_thread(conn, body.title)


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, conn=Depends(get_app_state)) -> dict:
    if state.get_chat_thread(conn, thread_id) is None:
        raise HTTPException(404, f"no conversation {thread_id}")
    if _active_chat_job(conn, thread_id):
        raise HTTPException(409, "conversation has an active chat turn")
    if not state.delete_chat_thread(conn, thread_id):
        raise HTTPException(404, f"no conversation {thread_id}")
    return {"deleted": thread_id}


@router.get("/threads/{thread_id}/messages")
def list_messages(thread_id: str, conn=Depends(get_app_state)) -> dict:
    if state.get_chat_thread(conn, thread_id) is None:
        raise HTTPException(404, f"no conversation {thread_id}")
    messages = state.chat_messages(conn, thread_id)
    # Logs remain in the owning job. Derive events when a saved thread opens
    # rather than duplicating a mutable transcript in each message row.
    logs = {row["message_id"]: row["log"] for row in conn.execute(
        "SELECT m.message_id, j.log FROM chat_messages m JOIN jobs j ON j.job_id = m.job_id"
        " WHERE m.thread_id = ? AND m.role = 'agent'", (thread_id,))}
    for message in messages:
        if message["message_id"] in logs:
            message["feed"] = livefeed.feed_of(logs[message["message_id"]] or "")
    out: dict[str, object] = {"items": messages}
    active = _active_chat_job(conn, thread_id)
    if active:
        out["job_id"] = active
    return out


@router.post("/threads/{thread_id}/messages")
def post_message(
    thread_id: str, body: MessageRequest,
    request: Request, conn=Depends(get_app_state),
) -> dict:
    """Store the reader's question, then start the job that answers it.

    The message is written before the job is submitted, so a question asked the
    moment before a crash is a row that says what was asked, not a question
    that never existed.
    """
    if state.get_chat_thread(conn, thread_id) is None:
        raise HTTPException(404, f"no conversation {thread_id}")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "a question needs words")
    message = state.add_chat_message(conn, thread_id, role="reader", text=text)
    state.title_chat_thread(conn, thread_id, text)
    runner = request.app.state.jobs
    job_id = runner.submit("chat_ask", {
        "thread_id": thread_id,
        "message_id": message["message_id"],
        "text": text,
        "harness": body.harness,
        "backend": body.backend,
    })
    return {"message_id": message["message_id"], "job_id": job_id, "kind": "chat_ask"}
