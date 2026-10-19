"""The relay's HTTP API. One relay serves one reader, and the reader is whoever holds the token."""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import re
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import pricewatch

from . import __version__, push as pusher, safefetch, store as storage, watcher
from .settings import Settings

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")
WATCH = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = authorization[7:].strip()
    try:
        if len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) != 32:
            raise ValueError
    except (binascii.Error, ValueError) as error:
        raise HTTPException(401, "that is not an owner token") from error
    return token


class Claim(BaseModel):
    topic: str = Field(default="", max_length=64)


class WatchBody(BaseModel):
    url: str = Field(max_length=2000)
    label: str = Field(default="", max_length=storage.MAX_LABEL)
    target: float | None = Field(default=None, ge=0, lt=1e10)
    drop_pct: float | None = Field(default=None, gt=0, lt=100)
    started_price: float | None = Field(default=None, ge=0, lt=1e10)
    currency: str = Field(default="", max_length=8)


#: A request that is not a blob is a few hundred bytes of JSON.
SMALL_BODY = 16 * 1024


class BodyLimit:
    """Refuse an oversized body before anything reads it, whoever sent it.

    FastAPI reads and validates a request's body before it runs the owner check, so a
    stranger's 300 MB `PUT` was buffered whole (a gigabyte of memory) and only then
    answered. A blob may be as large as the operator allows; everything else is small.
    """

    def __init__(self, app, *, blob_bytes: int) -> None:  # type: ignore[no-untyped-def]
        self.app, self.blob_bytes = app, blob_bytes

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.blob_bytes if scope["path"].startswith("/v1/blob/") else SMALL_BODY
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._refuse(send)
            return
        seen = 0
        exceeded = False
        answered = False

        async def counted():  # type: ignore[no-untyped-def]
            # Past the limit the app is handed an empty, finished body and nothing more.
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def replying(message) -> None:  # type: ignore[no-untyped-def]
            # Whatever the app then says about a body it never got is replaced by the 413.
            nonlocal answered
            if not exceeded:
                await send(message)
            elif not answered:
                answered = True
                await self._refuse(send)

        await self.app(scope, counted, replying)

    @staticmethod
    async def _refuse(send) -> None:  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"detail":"too large"}'})


def create_app(settings: Settings | None = None, *, fetch=safefetch.markup, push=pusher.send,
               sweeper: bool = False) -> FastAPI:
    config = settings or Settings()
    db = storage.Store(config.db_path, config.secret)
    stop = threading.Event()

    def run_sweeps() -> None:
        while not stop.wait(max(60, config.sweep_minutes * 60)):
            try:
                watcher.sweep(db, fetch, push, ntfy_base=config.ntfy_base)
            except Exception:  # noqa: BLE001 - the clock must outlive one bad sweep
                log.warning("a sweep failed", exc_info=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if sweeper:
            threading.Thread(target=run_sweeps, name="sweeps", daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="Kriko relay", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.db, app.state.config = db, config
    app.add_middleware(BodyLimit, blob_bytes=config.max_blob_bytes)

    def owner(authorization: str | None = Header(default=None)) -> None:
        try:
            db.check(_token(authorization))
        except storage.Denied as error:
            raise HTTPException(403, "that token is not this relay's owner") from error

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.put("/v1/owner")
    def claim(body: Claim, authorization: str | None = Header(default=None),
              setup: str | None = Header(default=None, alias="X-Kriko-Setup")):
        """Take this relay, or confirm that you already have it.

        The first call needs the operator's setup word, so a stranger who finds the
        address first cannot take it. A device paired later presents the same token and
        needs no word.
        """
        token = _token(authorization)
        if body.topic and not pusher.TOPIC.match(body.topic):
            raise HTTPException(422, "that is not a Kriko topic")
        try:
            db.check(token)
        except storage.Denied:
            pass
        else:
            db.claim(token, body.topic)  # the owner again: only the topic can change
            return {"claimed": False}
        with db.connect() as conn:
            taken = bool(conn.execute("SELECT 1 FROM owner").fetchone())
        if taken:
            raise HTTPException(403, "this relay already belongs to someone else")
        if not config.setup:
            raise HTTPException(403, "this relay has no setup word, so it cannot be claimed")
        if not setup or not hmac.compare_digest(setup.encode("latin-1", "replace"), config.setup.encode("utf-8")):
            time.sleep(0.5)  # a guess costs something
            raise HTTPException(403, "that is not this relay's setup word")
        try:
            return {"claimed": db.claim(token, body.topic)}
        except storage.Claimed as error:
            raise HTTPException(403, "this relay already belongs to someone else") from error

    @app.delete("/v1/owner", dependencies=[Depends(owner)])
    def release() -> dict:
        """Forget everything and free the relay for a new owner."""
        db.reset()
        return {"released": True}

    @app.get("/v1/blob/{name}", dependencies=[Depends(owner)])
    def read_blob(name: str):
        if not NAME.match(name):
            raise HTTPException(404, "no such blob")
        row = db.read_blob(name)
        if not row:
            raise HTTPException(404, "nothing stored under that name")
        return Response(bytes(row["body"]), media_type="application/octet-stream",
                        headers={"X-Kriko-Version": str(row["version"])})

    @app.put("/v1/blob/{name}", dependencies=[Depends(owner)])
    async def write_blob(name: str, request: Request,
                         if_match: int | None = Header(default=None, alias="X-Kriko-Expect")):
        if not NAME.match(name):
            raise HTTPException(404, "no such blob")
        body = await request.body()
        if len(body) > config.max_blob_bytes:
            raise HTTPException(413, "too large")
        try:
            return {"version": db.write_blob(name, body, if_match)}
        except storage.Conflict as error:
            raise HTTPException(409, f"it moved: version {error.args[0]}") from error
        except storage.Full as error:
            raise HTTPException(507, str(error)) from error

    @app.get("/v1/watches", dependencies=[Depends(owner)])
    def watches() -> dict:
        return {"items": db.watches()}

    @app.put("/v1/watch/{watch_id}", dependencies=[Depends(owner)])
    def put_watch(watch_id: str, body: WatchBody) -> dict:
        if not WATCH.match(watch_id):
            raise HTTPException(404, "no such watch")
        try:
            host = safefetch.check(body.url)
        except safefetch.Refused as error:
            raise HTTPException(422, f"this relay will not watch that address: {error}") from error
        try:
            hashed = db.put_watch(watch_id, pricewatch.strip_tracking(body.url), host, label=body.label,
                                  target=body.target, drop_pct=body.drop_pct, started_price=body.started_price,
                                  currency=body.currency.upper(), limit=config.max_watches)
        except storage.Full as error:
            raise HTTPException(507, str(error)) from error
        return {"watch_id": watch_id, "page": hashed}

    @app.delete("/v1/watch/{watch_id}", dependencies=[Depends(owner)])
    def drop_watch(watch_id: str) -> dict:
        if not db.drop_watch(watch_id):
            raise HTTPException(404, "no such watch")
        return {"deleted": watch_id}

    @app.get("/v1/alerts", dependencies=[Depends(owner)])
    def alerts(after: int = 0) -> dict:
        return {"items": db.alerts_after(max(0, after))}

    return app


def sweep_now(app: FastAPI, *, fetch=safefetch.markup, push=pusher.send, pause=time.sleep) -> dict:
    """One sweep, for tests and for an operator's cron."""
    return watcher.sweep(app.state.db, fetch, push, pause=pause, ntfy_base=app.state.config.ntfy_base)
