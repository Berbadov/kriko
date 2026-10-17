"""A site icon as bytes, for the desktop window.

The window cannot fetch, so it asks the engine for the host it is about to
draw. This is the one door to `app/favicon.py`: a host in, an image out, with
the cache beside the app state file rather than in the pack store. An icon is
interface state — it is not knowledge, must not change a pack's digest, and
must survive a pack being uninstalled.

Read-only, and deliberately so. It takes a host and nothing else: no URL, no
path, no size. A caller cannot use it to read a file or reach a port this app
would not reach anyway, because the destination is constrained by the engine's
own guard.
"""

from pathlib import Path

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app import favicon

router = APIRouter(prefix="/api", tags=["favicon"])


@router.get("/favicon")
def icon(request: Request, host: str = Query("", max_length=253)) -> Response:
    """The site's own icon, or a plain sentence saying there is none.

    A missing icon is ordinary — plenty of sites declare none and answer 404
    for both well-known names — so it is answered with a 404 body rather than
    an exception object. The window treats any non-200 as "keep the monogram".
    """
    name = host.strip()
    if not name:
        return PlainTextResponse("No site host was given.", status_code=404)
    cache = Path(request.app.state.settings.app_state_path).parent / "favicons"
    found = favicon.icon_for(name, cache_dir=cache)
    if found is None:
        return PlainTextResponse(
            f"No icon is available for {name}.", status_code=404
        )
    body, kind = found
    return Response(content=body, media_type=kind)
