import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.providers.termpty import SESSION
from app.web import origins
from app.web.settings import EXTENSION_PORT

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def terminal_ws(websocket: WebSocket) -> None:
    server = websocket.scope.get("server")
    if server is not None and server[1] == EXTENSION_PORT:
        await websocket.close(code=1008)
        return
    if not origins.terminal_origin_is_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        SESSION.start()
    except Exception as exc:
        # B109: the reader saw a bare "disconnected" with the reason only in
        # app.log (itself unreachable before the 0.7.6 log_config fix) — a
        # crash here is common (a missing shell, a packaging gap like
        # 0.7.4's winpty-agent.exe) and the one person who can act on it is
        # looking at the terminal panel, not a log file. Log it (so it is
        # still in app.log for a report) and say why on the socket itself,
        # in the same frame shape `pump_output` already uses, before closing
        # — no new protocol for the client to learn.
        logger.exception("terminal session failed to start")
        await websocket.send_text(
            json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        )
        await websocket.close(code=1011)
        return

    async def pump_output():
        while True:
            try:
                chunk = await asyncio.to_thread(SESSION.read)
            except (EOFError, OSError):
                break
            if not chunk:
                break
            await websocket.send_text(json.dumps({"type": "data", "data": chunk}))

    output_task = asyncio.create_task(pump_output())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("type") == "data":
                SESSION.write(msg.get("data", ""))
            elif msg.get("type") == "resize":
                SESSION.resize(int(msg.get("cols", 80)), int(msg.get("rows", 24)))
    except WebSocketDisconnect:
        pass
    finally:
        output_task.cancel()
