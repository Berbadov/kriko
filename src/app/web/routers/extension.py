"""The browser extension, from the app's side.

Read `app/extension.py` first — it holds the reasoning about what a native app
is and is not allowed to do here. This router is the thin part: three endpoints
over that module plus the sightings table, shaped so the UI can be a status
rather than a page of instructions.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app import extension
from app.web import state
from app.web.deps import get_app_state
from app.web.settings import EXTENSION_PORT

router = APIRouter(prefix="/api/extension", tags=["extension"])

#: A sighting older than this stops counting as "connected". The extension
#: polls on navigation rather than on a timer, so this is not a heartbeat
#: interval — it is how long a reader is willing to believe a thing they last
#: saw working an hour ago is still installed. Long enough to survive a session
#: of reading listings, short enough that removing the extension is noticed.
FRESH_SECONDS = 6 * 60 * 60


def _target(request: Request) -> Path:
    override = extension.env_override()
    if override:
        return override
    home = extension.home_of(request.app.state.settings.store_path)
    return extension.staged_dir(home)


def _age(iso: str) -> float | None:
    try:
        seen = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds()


@router.get("")
def status(request: Request, conn=Depends(get_app_state)) -> dict:
    """Everything the page needs to decide what to say, in one request.

    One call rather than four because the answers only mean anything together:
    "staged but never seen" and "seen but the port is taken" are different
    problems with different fixes, and a page that resolved them independently
    would flicker between two half-truths on every load.
    """
    source = extension.source_dir()
    target = _target(request)
    staged = (target / "manifest.json").is_file()
    sightings = state.extension_sightings(conn)
    ages = [age for row in sightings if (age := _age(row["last_at"])) is not None]
    fresh = min(ages) if ages else None

    return {
        "available": source is not None,
        "version": extension.version(source) if source else "",
        "staged": staged,
        "staged_version": extension.version(target) if staged else "",
        "path": str(target),
        # The extension cannot be told a port, so it hardcodes this one. If
        # something else on the machine holds it the extension will install
        # perfectly and reach nothing, which looks identical to a bad install
        # from the reader's side — so the page gets told, rather than guessing.
        "port": EXTENSION_PORT,
        "port_is_ours": bool(request.app.state.settings.extension_port_bound),
        "browsers": extension.browsers(),
        "sightings": sightings,
        "connected": fresh is not None and fresh < FRESH_SECONDS,
        # `connected` answers "is it live right now", which is right for the
        # badge on this page — a reader watching it wants to know the extension
        # is talking *today*. It is the wrong question for "has this reader
        # ever added the extension at all": a sighting older than FRESH_SECONDS
        # made that badge go stale, and a caller that reused it for onboarding
        # (B85) told someone whose extension has worked for weeks to go and
        # install it again the moment they left the app alone for six hours.
        # `sightings` is never pruned, so its presence is permanent evidence.
        "ever_connected": bool(sightings),
        "seconds_since_seen": fresh,
        # ── which extension is actually loaded ────────────────────────
        #
        # `version` above is what this app *carries* and `staged_version` is
        # what it wrote to disk. Neither is what the browser is running: an
        # unpacked extension is loaded once and stays loaded, so a reader can
        # sit on a months-old copy while both of those numbers read current.
        # That is the whole of B73 — a stale extension fails in ways that look
        # like a broken app, and nothing here could tell the difference.
        #
        # Taken from the newest sighting that named a version rather than the
        # newest sighting: two browsers may both have called, and the one that
        # cannot say what it is has nothing to contribute to the question.
        "compatibility": extension.compatibility(
            _running_version(sightings),
            extension.version(source) if source else "",
        ),
    }


def _running_version(sightings: list[dict]) -> str:
    for row in sightings:  # newest contact first
        if row.get("version"):
            return str(row["version"])
    return ""


@router.post("/stage")
def stage(request: Request) -> dict:
    """Put a loadable copy of the extension on disk and say where.

    Idempotent, and safe to press again: that is the repair path when an app
    update ships a newer extension than the folder Chrome is holding.
    """
    source = extension.source_dir()
    if source is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "this build does not carry the browser extension — it is added "
                "to the bundle by packaging/kriko-sidecar.spec"
            ),
        )
    target = _target(request)
    try:
        written = extension.stage(source, target)
    except OSError as cause:
        raise HTTPException(status_code=500, detail=f"could not write {target}: {cause}")
    return {"path": str(target), "written": written, "version": extension.version(target)}


@router.post("/reveal")
def reveal(request: Request) -> dict:
    """Open the staged folder in the file manager.

    A convenience with a fallback, never a requirement: the response carries
    the path either way, because the reader's next action is pasting it.
    """
    target = _target(request)
    if not target.is_dir():
        raise HTTPException(status_code=409, detail="nothing staged yet — add it first")
    return {"path": str(target), "error": extension.reveal(target)}


@router.post("/launch")
def launch(request: Request) -> dict:
    """Stage the extension and open a browser that already has it loaded.

    The one click. One request rather than two because a reader's single press
    must not be able to half-succeed: `/stage` then `/launch` can leave files
    written and no window opened, which reads as "the button did nothing".

    Never an error status. Both ways this can fall short — no Chromium on the
    machine, or a browser that refuses to start — are things to *tell* the
    reader on a page that already carries the manual steps, and a 500 would
    replace those steps with a red banner. The files are staged either way,
    because that is what the manual path needs and this reader has already
    asked for the extension.

    Success is not claimed here. A Chrome build that ignores `--load-extension`
    opens an ordinary window and says nothing; the extension's own call to
    `/api/adapters` is the only proof, the status endpoint above already
    reports it, and the page keeps watching until it lands.
    """
    source = extension.source_dir()
    if source is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "this build does not carry the browser extension — it is added "
                "to the bundle by packaging/kriko-sidecar.spec"
            ),
        )

    target = _target(request)
    try:
        extension.stage(source, target)
    except OSError as cause:
        raise HTTPException(status_code=500, detail=f"could not write {target}: {cause}")

    home = extension.home_of(request.app.state.settings.store_path)
    profile = extension.profile_dir(home)
    note = (
        "The window is a separate browser profile — it has to be, because a "
        "browser that is already running ignores an extension handed to it on "
        "the command line. Your bookmarks and logins are not in it."
    )

    browser = extension.find_chromium()
    if browser is None:
        return {
            "launched": False,
            "browser": "",
            "path": str(target),
            "profile": str(profile),
            "note": note,
            "error": (
                "No Chrome, Chromium, Brave or Edge found on this machine. "
                "Firefox cannot be handed an extension this way — the steps "
                "below are the install for it."
            ),
        }

    # This app's own extension page, served by this process, so it works with
    # no network: the browser opens on the screen where the check-in
    # confirmation appears. The proof of the install is the first thing the
    # reader sees rather than something they have to come back to.
    landing = f"{str(request.base_url).rstrip('/')}/#/extension"
    error = extension.launch_with_extension(browser, target, profile, landing=landing)
    return {
        "launched": not error,
        "browser": browser,
        "path": str(target),
        "profile": str(profile),
        "note": note,
        "error": error,
    }
