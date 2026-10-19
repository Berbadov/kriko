"""The relay's HTTP API. Every route is under one group, and a group is its token."""

from __future__ import annotations

import base64
import binascii
import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import replace

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import pricewatch

from . import __version__, push as pusher, safefetch, store as storage, watcher
from .settings import Settings

log = logging.getLogger(__name__)

GROUP = re.compile(r"^[0-9a-f]{32}$")
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")
WATCH = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class Limiter:
    """`allowed` is true for the first `count` calls per key per hour. In memory, on purpose."""

    def __init__(self, count: int, window: float = 3600.0, clock=time.monotonic):
        self.count, self.window, self.clock = count, window, clock
        self.seen: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allowed(self, key: str) -> bool:
        now = self.clock()
        with self.lock:
            hits = self.seen[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.count:
                return False
            hits.append(now)
            return True


def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "a bearer token is required")
    token = authorization[7:].strip()
    try:
        if len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) != 32:
            raise ValueError
    except (binascii.Error, ValueError) as error:
        raise HTTPException(401, "that is not a group token") from error
    return token


class Register(BaseModel):
    topic: str = Field(default="", max_length=64)


class WatchBody(BaseModel):
    url: str = Field(max_length=2000)
    label: str = Field(default="", max_length=storage.MAX_LABEL)
    target: float | None = Field(default=None, ge=0, lt=1e10)
    drop_pct: float | None = Field(default=None, gt=0, lt=100)
    started_price: float | None = Field(default=None, ge=0, lt=1e10)
    currency: str = Field(default="", max_length=8)


def create_app(settings: Settings | None = None, *, fetch=safefetch.markup, push=pusher.send,
               sweeper: bool = False) -> FastAPI:
    config = settings or Settings()
    db = storage.Store(config.db_path, config.secret)
    limiter = Limiter(config.registrations_per_hour)
    stop = threading.Event()

    def run_sweeps() -> None:
        while not stop.wait(max(60, config.sweep_minutes * 60)):
            try:
                watcher.sweep(db, fetch, push, ntfy_base=config.ntfy_base)
                db.forget_idle(config.forget_after_days)
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

    def member(group: str, authorization: str | None = Header(default=None)) -> str:
        if not GROUP.match(group):
            raise HTTPException(404, "no such group")
        try:
            db.check(group, _token(authorization))
        except storage.Denied as error:
            raise HTTPException(403, "that token is not this group's") from error
        return group

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.put("/v1/g/{group}")
    def register(group: str, body: Register, request: Request, authorization: str | None = Header(default=None)):
        """Create the group, or confirm it. The first call fixes the token; the group is nothing else."""
        if not GROUP.match(group):
            raise HTTPException(404, "no such group")
        token = _token(authorization)
        if body.topic and not pusher.TOPIC.match(body.topic):
            raise HTTPException(422, "that is not a Kriko topic")
        host = request.client.host if request.client else "?"
        known = False
        try:
            with db.connect() as conn:
                known = bool(conn.execute("SELECT 1 FROM groups WHERE group_id = ?", (group,)).fetchone())
            if not known and not limiter.allowed(host):
                raise HTTPException(429, "too many new groups from this address; try again later")
            created = db.register(group, token, body.topic, max_groups=config.max_groups)
        except storage.Denied as error:
            raise HTTPException(403, "that token is not this group's") from error
        except storage.Full as error:
            raise HTTPException(507, str(error)) from error
        return {"created": created}

    @app.get("/v1/g/{group}/blob/{name}")
    def read_blob(name: str, group: str = Depends(member)):
        if not NAME.match(name):
            raise HTTPException(404, "no such blob")
        row = db.read_blob(group, name)
        if not row:
            raise HTTPException(404, "nothing stored under that name")
        return Response(bytes(row["body"]), media_type="application/octet-stream",
                        headers={"X-Kriko-Version": str(row["version"])})

    @app.put("/v1/g/{group}/blob/{name}")
    async def write_blob(name: str, request: Request, group: str = Depends(member),
                         if_match: int | None = Header(default=None, alias="X-Kriko-Expect")):
        if not NAME.match(name):
            raise HTTPException(404, "no such blob")
        body = await request.body()
        if len(body) > config.max_blob_bytes:
            raise HTTPException(413, "too large")
        try:
            return {"version": db.write_blob(group, name, body, if_match)}
        except storage.Conflict as error:
            raise HTTPException(409, f"it moved: version {error.args[0]}") from error
        except storage.Full as error:
            raise HTTPException(507, str(error)) from error

    @app.get("/v1/g/{group}/watches")
    def watches(group: str = Depends(member)) -> dict:
        return {"items": db.watches_of(group)}

    @app.put("/v1/g/{group}/watch/{watch_id}")
    def put_watch(watch_id: str, body: WatchBody, group: str = Depends(member)) -> dict:
        if not WATCH.match(watch_id):
            raise HTTPException(404, "no such watch")
        try:
            host = safefetch.check(body.url)
        except safefetch.Refused as error:
            raise HTTPException(422, f"this relay will not watch that address: {error}") from error
        clean = pricewatch.strip_tracking(body.url)
        try:
            hashed = db.put_watch(group, watch_id, clean, host, label=body.label, target=body.target,
                                  drop_pct=body.drop_pct, started_price=body.started_price,
                                  currency=body.currency.upper(), max_per_group=config.max_watches_per_group,
                                  max_pages=config.max_pages)
        except storage.Full as error:
            raise HTTPException(507, str(error)) from error
        return {"watch_id": watch_id, "page": hashed}

    @app.delete("/v1/g/{group}/watch/{watch_id}")
    def drop_watch(watch_id: str, group: str = Depends(member)) -> dict:
        if not db.drop_watch(group, watch_id):
            raise HTTPException(404, "no such watch")
        return {"deleted": watch_id}

    @app.get("/v1/g/{group}/alerts")
    def alerts(after: int = 0, group: str = Depends(member)) -> dict:
        return {"items": db.alerts_after(group, max(0, after))}

    @app.delete("/v1/g/{group}")
    def forget(group: str = Depends(member)) -> dict:
        db.forget_group(group)
        return {"forgotten": True}

    return app


def sweep_now(app: FastAPI, *, fetch=safefetch.markup, push=pusher.send, pause=time.sleep) -> dict:
    """One sweep, for tests and for an operator's cron."""
    config = replace(app.state.config)
    return watcher.sweep(app.state.db, fetch, push, pause=pause, ntfy_base=config.ntfy_base)
