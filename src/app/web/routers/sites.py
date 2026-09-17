"""Which sites this installation can read, and how it learns a new one.

`app/sites.py` holds the reasoning — why a learned adapter lives in
`app.sqlite` and never in the store, and why it always loses to a pack's. This
is the door: what is registered, what has been asked for, and the button that
turns the second into the first.

The reader's sentence this exists for: *"I cannot open the extension on pages
that aren't registered, so basically it opens on sahibinden only."*
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import sites
from app.web import state
from app.web.deps import get_app_state, get_store

router = APIRouter(prefix="/api", tags=["sites"])


class SeenRequest(BaseModel):
    """A page the reader stood on and pressed the button.

    `url` is kept for one reason: an agent asked to write the adapter needs a
    real page to read, and "somewhere on that site" is not one. It is a single
    sample per host, replaced — not browsing history.
    """

    url: str = Field(min_length=4, max_length=2000)
    title: str = Field("", max_length=500)


class ActivationRow(BaseModel):
    """One site, as the extension's own reconciliation left it."""

    site: str = Field(max_length=253)
    #: `active` | `pending` | `refused` — the extension's words, kept rather
    #: than translated here, so a new state it learns to report arrives as
    #: itself instead of as whatever this file guessed it meant.
    state: str = Field("", max_length=32)
    detail: str = Field("", max_length=500)
    pattern: str = Field("", max_length=200)


class ActivationReport(BaseModel):
    sites: list[ActivationRow] = Field(default_factory=list, max_length=500)


class RegisterRequest(BaseModel):
    url: str = Field("", max_length=2000)
    #: Whose identity keys the adapter maps into. Empty means "whichever pack
    #: the agent judges this site sells the products of", which it states in
    #: the adapter it writes.
    pack_id: str = Field("", max_length=200)


@router.get("/sites")
def list_sites(store=Depends(get_store), conn=Depends(get_app_state)) -> dict:
    """Everything readable here, plus the sites somebody asked for and cannot be.

    The two lists are defined in `sites.TWO_LISTS`, and the second is *derived*
    from the first. It used to be a straight read of the table, which left a
    registered site sitting in both at once with the same URL in each — the
    reader's report, and a screen contradicting itself.

    `activation` rides along because "readable" and "the panel appears" are not
    the same fact and the screen was only ever shown the first.
    """
    rows = sites.registered(store, conn)
    for row in rows:
        row["activation"] = sites.activation(store, conn, row["site"])
    return {
        "registered": rows,
        "requested": sites.requested(store, conn),
    }


@router.get("/sites/{host}/activation")
def site_activation(host: str, store=Depends(get_store),
                    conn=Depends(get_app_state)) -> dict:
    """Will the panel appear on this host — and if not, name the blocker.

    The reader registered a site, was told Kriko recognised it, reloaded, and
    nothing happened. Nothing was broken except the *reporting*: the host
    permission had never been granted, because only a gesture inside the
    extension can grant one. This is the endpoint that says so.
    """
    return sites.activation(store, conn, host)


@router.post("/sites/activation")
def report_activation(body: ActivationReport, conn=Depends(get_app_state)) -> dict:
    """The extension telling the app what its last sync actually achieved.

    One direction only, and it has to be this one: the browser is the only
    thing that knows whether a permission was granted, and the app is the only
    thing with a screen to say it on.
    """
    written = state.record_activation(conn, [one.model_dump() for one in body.sites])
    return {"recorded": written}


@router.post("/sites/seen")
def site_seen(
    body: SeenRequest, store=Depends(get_store), conn=Depends(get_app_state)
) -> dict:
    """The extension reporting a page nothing here can read.

    Answers with whether it is in fact readable, because the extension asks
    this at exactly the moment the reader pressed the button and the honest
    answers are different: "this site works, the panel should be there" is a
    bug report, and "nothing here reads this site" is an offer.
    """
    host = sites.host_of(body.url)
    if not host:
        raise HTTPException(422, f"{body.url!r} has no hostname in it")
    found = sites.adapter_for(store, conn, body.url)
    if found is not None:
        return {"host": host, "readable": True, "adapter": found.get("id", "")}
    row = state.record_site_request(conn, host=host, url=body.url, title=body.title)
    return {"host": host, "readable": False, "request": row}


@router.post("/sites/{host}/register")
def register_site(
    host: str, body: RegisterRequest, request: Request, conn=Depends(get_app_state)
) -> dict:
    """Ask an agent to work out how to read this site. Returns a job id.

    An operation, not a form: somebody has to read the page. What comes back is
    checked by `sites.check` before it is stored, because an adapter's `site`
    becomes a permission in a browser.
    """
    wanted = sites.host_of(host)
    if not wanted:
        raise HTTPException(422, f"{host!r} is not a hostname")
    known = {row["host"] for row in state.site_requests(conn)}
    url = body.url or next(
        (row["sample_url"] for row in state.site_requests(conn)
         if row["host"] == wanted), ""
    )
    if not url and wanted not in known:
        url = f"https://{wanted}/"
    job_id = request.app.state.jobs.submit(
        "site_register", {"host": wanted, "url": url, "pack_id": body.pack_id}
    )
    state.set_site_request(conn, wanted, state="working", detail="")
    return {"job_id": job_id, "kind": "site_register", "host": wanted}


@router.delete("/sites/{host}")
def forget_site(host: str, conn=Depends(get_app_state)) -> dict:
    """Throw away an adapter this installation learned. Packs are untouched."""
    wanted = sites.host_of(host)
    if not wanted:
        raise HTTPException(422, f"{host!r} is not a hostname")
    return {"host": wanted, "forgotten": state.forget_local_adapter(conn, wanted)}
