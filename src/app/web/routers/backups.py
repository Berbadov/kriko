"""Snapshot transfer through the desktop JSON bridge; restore needs a restart."""

import base64
import binascii
import sqlite3
import zipfile

from fastapi import APIRouter, HTTPException, Request

from app import backups
from app.web import state
from app.web.routers.packs import ArtifactUpload

router = APIRouter(prefix="/api/backups", tags=["backups"])


def _idle(request: Request) -> None:
    settings = request.app.state.settings
    conn = state.connect(settings.app_state_path)
    try:
        active = conn.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','cancelling')").fetchone()[0]
        if active or state.running_operations(conn):
            raise HTTPException(409, "Finish or stop active research before making or restoring a snapshot.")
    finally:
        conn.close()


@router.post("/export")
def export_snapshot(request: Request) -> dict:
    _idle(request)
    try:
        data = backups.export(request.app.state.settings)
    except (ValueError, OSError, sqlite3.Error) as error:
        raise HTTPException(409, str(error)) from error
    return {"filename": "kriko-snapshot.zip", "data": base64.b64encode(data).decode("ascii")}


@router.post("/restore")
def stage_restore(body: ArtifactUpload, request: Request) -> dict:
    _idle(request)
    try:
        raw = base64.b64decode(body.data, validate=True)
        return backups.stage(request.app.state.settings, raw)
    except (ValueError, binascii.Error, OSError, sqlite3.Error, zipfile.BadZipFile, KeyError) as error:
        raise HTTPException(422, str(error)) from error
