import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.providers.termpty import SESSION
from app.web import origins
from app.web.settings import EXTENSION_PORT

router = APIRouter(prefix="/api/terminal", tags=["terminal"])


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
    SESSION.start()

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
