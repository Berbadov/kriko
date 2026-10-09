"""The app's own updates: ask, then fetch.

`GET` only looks (and fails quiet); `POST /download` is what the reader asked
for and returns the verified installer's path. Running it is the desktop
shell's job, because only the shell can close the app the installer replaces.
"""

from fastapi import APIRouter, HTTPException, Request

from app import appupdate
from app.version import app_version

router = APIRouter(prefix="/api/app-update", tags=["app-update"])


@router.get("")
def status(request: Request) -> dict:
    return appupdate.check(request.app.state.settings.app_release_api_url, app_version())


@router.post("/download")
def download(request: Request) -> dict:
    info = appupdate.check(request.app.state.settings.app_release_api_url, app_version())
    if info.get("error"):
        raise HTTPException(status_code=502, detail=info["error"])
    if not info["newer"]:
        raise HTTPException(status_code=409, detail="this is already the newest version")
    try:
        path = appupdate.download(info)
    except (ValueError, OSError) as cause:
        raise HTTPException(status_code=502, detail=str(cause))
    return {"path": str(path), "version": info["version"]}
