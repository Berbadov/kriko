"""Which sites this installation can read, and how it learns a new one.

`app/sites.py` holds the reasoning — why a learned adapter lives in
`app.sqlite` and never in the store, and why it always loses to a pack's. This
is the door: what is registered, what has been asked for, and the button that
turns the second into the first.

The reader's sentence this exists for: *"I cannot open the extension on pages
that aren't registered, so basically it opens on one site only."*
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import sites, siteinfer
from app.web import state
from app.web.deps import get_app_state, get_store

router = APIRouter(prefix="/api", tags=["sites"])


class SeenRequest(BaseModel):
    """A page the reader stood on and pressed the button.

    `url` is kept for one reason: an agent asked to write the adapter needs a
    real page to read, and "somewhere on that site" is not one. It is a single
    sample per host, replaced — not browsing history.

    `fields`, `description` and `product` are what the extension read on that
    page. They are the page already rendered and already past the site's bot
    check, which is the one thing an agent fetching the URL cannot have; they
    travel with the ask so the learning run can use them instead.
    """

    url: str = Field(min_length=4, max_length=2000)
    title: str = Field("", max_length=500)
    #: The page's own label -> value pairs, as the scraper read them.
    fields: dict[str, str] = Field(default_factory=dict)
    description: str = Field("", max_length=5000)
    #: The product the page named, when it published structured data.
    product: dict = Field(default_factory=dict)
    page_title: str = Field("", max_length=500)


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
    harness: str = Field("", max_length=64)
    #: Whose identity keys the adapter maps into. Empty means "whichever pack
    #: the agent judges this site sells the products of", which it states in
    #: the adapter it writes.
    pack_id: str = Field("", max_length=200)


class InferredRequest(BaseModel):
    """Whether an adapter this installation inferred may be used."""

    enabled: bool = True


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
    body: SeenRequest, request: Request,
    store=Depends(get_store), conn=Depends(get_app_state),
) -> dict:
    """The extension reporting a page nothing here can read.

    Answers with whether it is in fact readable, because the extension asks
    this at exactly the moment the reader pressed the button and the honest
    answers are different: "this site works, the panel should be there" is a
    bug report, and "nothing here reads this site" is an offer.

    The press is also where the browser's richest snapshot of a page arrives —
    the explore scrape, which is the page's own label/value shapes and the
    structured data it publishes — so it is put to this machine's model before
    the site is filed as one to ask an agent about (`app/siteinfer.py`). When
    no model is ready the offer below is exactly what it was.
    """
    host = sites.host_of(body.url)
    if not host:
        raise HTTPException(422, f"{body.url!r} has no hostname in it")
    found = sites.adapter_for(store, conn, body.url)
    if found is not None:
        return {"host": host, "readable": True, "adapter": found.get("id", "")}
    inferred = siteinfer.infer(
        store, conn, app_state_path=request.app.state.settings.app_state_path,
        url=body.url, fields=body.fields, title=body.page_title or body.title,
        description=body.description,
        product_name=str((body.product or {}).get("name") or ""),
    )
    if inferred is not None:
        # Readable now, and by something nobody wrote. `inferred` rides the
        # answer so the panel can say where the site came from instead of
        # reporting a site that appeared by itself.
        return {"host": host, "readable": True, "inferred": True,
                "adapter": inferred.get("id", "")}
    row = state.record_site_request(
        conn, host=host, url=body.url, title=body.title,
        sample=sites.sample(
            url=body.url, title=body.page_title or body.title,
            fields=body.fields, description=body.description, product=body.product),
    )
    return {"host": host, "readable": False, "request": row}


class LearnRequest(SeenRequest):
    """The reader pressing "Learn this page" in the panel.

    `agent` is the one the panel has picked: empty or `local` is this machine's
    model, answered at once; anything else is that agent, which takes minutes
    and so comes back as a job to follow.
    """

    agent: str = Field("", max_length=64)


@router.post("/sites/learn")
def learn_page(
    body: LearnRequest, request: Request,
    store=Depends(get_store), conn=Depends(get_app_state),
) -> dict:
    """Go through this page and learn what to take from it.

    The extension's explore snapshot is the page: its labels and values, and the
    structured data it publishes. The agent maps them onto what installed packs
    know (`sites.check` and `sites.validate_sample` still decide whether to
    keep it). The answer says what was taken and under which name, so the
    reader sees what "learned" means instead of taking it on trust.
    """
    from app import pagetitle, prefs

    host = sites.host_of(body.url)
    if not host:
        raise HTTPException(422, f"{body.url!r} has no hostname in it")
    named = pagetitle.product_name(
        str((body.product or {}).get("name") or "") or body.page_title or body.title, body.url)
    agent = body.agent.strip()
    if agent and agent != prefs.LOCAL_PICK:
        sample = sites.sample(
            url=body.url, title=body.page_title or body.title, fields=body.fields,
            description=body.description, product=body.product)
        state.record_site_request(conn, host=host, url=body.url, title=body.title, sample=sample)
        job_id = request.app.state.jobs.submit(
            "site_register",
            {"host": host, "url": body.url, "harness": agent, "pack_id": "", "sample": sample})
        state.set_site_request(conn, host, state="working", detail="")
        return {"host": host, "mode": "agent", "agent": agent, "name": named,
                "job_id": job_id, "kind": "site_register"}
    lesson = siteinfer.learn(
        store, conn, app_state_path=request.app.state.settings.app_state_path,
        url=body.url, fields=body.fields, title=body.page_title or body.title,
        description=body.description, product_name=str((body.product or {}).get("name") or ""),
        timeout=siteinfer.PRESS_TIMEOUT)
    read = lesson.get("read") or {}
    return {
        "host": host, "mode": "local", "name": named,
        "learned": bool(lesson["learned"]), "reason": lesson["reason"],
        "model": lesson.get("model", ""),
        "adapter": (lesson.get("spec") or {}).get("id", ""),
        # What the page gave and what it was taken as: the lesson, in the open.
        "grabs": [{"as": str(key), "value": str(value)[:120], "kind": group}
                  for group in ("identity", "context")
                  for key, value in (read.get(group) or {}).items()],
    }


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
        "site_register", {**body.model_dump(), "host": wanted, "url": url}
    )
    state.set_site_request(conn, wanted, state="working", detail="")
    return {"job_id": job_id, "kind": "site_register", "host": wanted}


@router.post("/sites/{host}/inferred")
def set_inferred(
    host: str, body: InferredRequest, conn=Depends(get_app_state)
) -> dict:
    """Turn an adapter this installation inferred off — or back on.

    The reader's control over the one piece of site knowledge nobody wrote. An
    inferred adapter is a model's guess about the shape of a page; it earns a
    host permission and an injection target exactly like a pack's, and "I did
    not ask for this on this site" has to be answerable without deleting a pack
    or editing a file. Off is not forgotten: the row and its inference stay, so
    the switch works both ways and the same page shape is not put to the model
    again.

    Only an inferred adapter can be turned off here. An agent's or a reader's
    own is theirs, and a route that quietly disabled one would be this screen
    overriding a decision somebody made on purpose — that is what the DELETE
    beside it is for.
    """
    wanted = sites.host_of(host)
    if not wanted:
        raise HTTPException(422, f"{host!r} is not a hostname")
    inferred = [row for row in sites.local_rows(conn, enabled_only=False)
                if row["host"] == wanted and row.get("source") == "inference"]
    if not inferred:
        raise HTTPException(404, f"nothing on {wanted} was inferred here")
    return {
        "host": wanted,
        "enabled": body.enabled,
        "changed": state.set_local_adapter_enabled(conn, wanted, body.enabled),
    }


@router.delete("/sites/{host}")
def forget_site(host: str, conn=Depends(get_app_state)) -> dict:
    """Throw away an adapter this installation learned. Packs are untouched."""
    wanted = sites.host_of(host)
    if not wanted:
        raise HTTPException(422, f"{host!r} is not a hostname")
    return {"host": wanted, "forgotten": state.forget_local_adapter(conn, wanted)}
