"""The browser extension, from the app's side.

Read `app/extension.py` first — it holds the reasoning about what a native app
is and is not allowed to do here. This router is the thin part: four endpoints
over that module plus the sightings table, shaped so the UI can be a status
rather than a page of instructions.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import extension, keys, sites
from app.web import state
from app.web.deps import get_app_state, get_jobs, get_store
from app.web.routers.research import resolve_research_subject
from kriko.research.agent import AgentResearcher
from kriko.research.api import ApiResearcher

router = APIRouter(prefix="/api/extension", tags=["extension"])

#: The extension door's own spending cap (2026-09-09-knowledge-building-design.md
#: §3). Nothing in this codebase yet computes a per-subject cost estimate for
#: the api plane (that is Phase 2/3 work), so this is not an estimate — it is
#: the number this endpoint tells `POST /api/research` to enforce for a run
#: started from a listing page, chosen small enough that an unattended click
#: from a browser panel cannot become a surprise. Raise it in Settings →
#: Research once that screen exists, not here.
EXTENSION_RESEARCH_BUDGET_USD = 0.20

#: A sighting older than this stops counting as "connected". The extension
#: polls on navigation rather than on a timer, so this is not a heartbeat
#: interval — it is how long a reader is willing to believe a thing they last
#: saw working an hour ago is still installed. Long enough to survive a session
#: of reading listings, short enough that removing the extension is noticed.
FRESH_SECONDS = 6 * 60 * 60


def _target(request: Request) -> Path:
    return extension.target_for(request.app.state.settings.store_path)


def _age(iso: str) -> float | None:
    try:
        seen = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - seen).total_seconds()


def _loaded_digest(request: Request, sightings: list[dict]) -> str:
    """The file digest the most recently seen extension said it runs."""
    loaded = getattr(request.app.state, "extension_digests", {})
    for row in sightings:
        digest = (loaded.get(row["origin"]) or {}).get("content_digest", "")
        if digest:
            return digest
    return ""


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
    firefox_target = extension.target_for(request.app.state.settings.store_path, "firefox")
    staged = (target / "manifest.json").is_file()
    sightings = state.extension_sightings(conn)
    ages = [age for row in sightings if (age := _age(row["last_at"])) is not None]
    fresh = min(ages) if ages else None

    return {
        "available": source is not None,
        "version": extension.version(source) if source else "",
        "staged": staged,
        "staged_version": extension.version(target) if staged else "",
        "content_digest": extension.content_digest(source) if source else "",
        "staged_content_digest": extension.content_digest(target) if staged else "",
        "staged_files": extension.content_files(target) if staged else [],
        "loaded_files": [
            {"origin": row["origin"], **getattr(request.app.state, "extension_digests", {}).get(
                row["origin"], {"content_digest": "", "version": row.get("version", "")})}
            for row in sightings
        ],
        "path": str(target),
        "firefox": {
            "path": str(firefox_target),
            "manifest_path": str(firefox_target / "manifest.json"),
            "package_path": str(firefox_target.with_suffix(".xpi")),
            "staged": (firefox_target / "manifest.json").is_file(),
            "signed": False,
        },
        # The extension cannot be told a port, so it hardcodes this one. If
        # something else on the machine holds it the extension will install
        # perfectly and reach nothing, which looks identical to a bad install
        # from the reader's side — so the page gets told, rather than guessing.
        "port": request.app.state.settings.extension_port,
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
            loaded_digest=_loaded_digest(request, sightings),
            carried_digest=extension.content_digest(source, "firefox" if sightings and
                sightings[0]["origin"].startswith("moz-extension://") else "chromium") if source else "",
        ),
    }


@router.get("/research-plane")
def research_plane(request: Request) -> dict:
    """Which research plane a run started from the panel would use, and what
    it costs — never a key.

    The panel's "Research it" prompt has to name the cost *before* the reader
    clicks it (2026-09-09-knowledge-building-design.md §3), and it cannot read
    a key to decide that: an endpoint on this port that returned a key would
    be a key the extension's origin — any page it is running on — could read
    too. So this reuses `app.keys.status` — the same presence-only read `GET
    /api/keys` already serves — for whether the api plane is even reachable,
    and reports the plane name and `cost_basis` `kriko.research.get_researcher`
    would act on, plus the cap this door enforces on the api plane. Nothing
    else, and no key.
    """
    settings = request.app.state.settings
    env_path = keys.env_path(getattr(settings, "app_state_path").parent)
    from app import prefs
    from app.web.tasks import default_plane

    # The local machine plane goes first when it is ready and the reader has
    # not picked an agent (B172): a model on this computer costs nothing and
    # needs no account, so it is what an unnamed run gets. `default_plane` is
    # the one rule `default_backend` uses too, so the door and the app agree.
    chosen, why = default_plane(getattr(settings, "app_state_path", None))
    if chosen == "local":
        return {"backend": "local", "cost_basis": "self_hosted",
                "budget_usd": 0.0, "why": why}
    # With the model the run would use: a key saved for the API agent alone
    # must not route the reader onto a paid plane that fails at its first page.
    if prefs.paid_plane_ready(getattr(settings, "app_state_path", None), env_path):
        return {
            "backend": ApiResearcher.name,
            "cost_basis": ApiResearcher.cost_basis,
            "budget_usd": EXTENSION_RESEARCH_BUDGET_USD,
        }
    from app.providers import agent_ready, bills_per_token

    path = getattr(settings, "app_state_path", None)
    if agent_ready(path):
        # The picked agent may be an API agent (B153), and then the run is
        # billed like the paid plane and capped by this door like it.
        if bills_per_token(path):
            return {
                "backend": "harness",
                "cost_basis": "per_token",
                "budget_usd": EXTENSION_RESEARCH_BUDGET_USD,
            }
        return {
            "backend": "harness",
            "cost_basis": "subscription",
            "budget_usd": 0.0,
        }
    return {
        "backend": AgentResearcher.name,
        "cost_basis": AgentResearcher.cost_basis,
        "budget_usd": 0.0,
    }


class ExtensionResearchRequest(BaseModel):
    q: str = Field("", max_length=500)
    subject_id: str = Field("", max_length=200)
    harness: str = Field("", max_length=200)
    model: str = Field("", max_length=200)
    search: str = Field("", max_length=64)
    cap: float | None = Field(None, gt=0, allow_inf_nan=False)
    allow_draft: bool = Field(False, strict=True)
    #: Queue runs need the installed draft; the listing's quick-look card is
    #: useful in the browser panel but would start a second visible job here.
    quick: bool = Field(True, strict=True)
    #: The listing the reader is on, so the quick look can hold itself to the
    #: pack whose site this is (its `research/principle.md`). Optional.
    url: str = Field("", max_length=2000)
    #: What the listing itself says (B150): its labelled facts and the
    #: seller's text, so the agents settle the exact version from the page
    #: rather than asking the reader for an engine code they may not know.
    #: Trimmed by `app.pagefacts.clean`; both optional.
    facts: dict[str, str] = Field(default_factory=dict)
    description: str = Field("", max_length=5000)


def _listing_pack(store, conn, url: str, facts: dict, title: str) -> str:
    """The pack whose adapter reads this listing best, or "".

    `adapter_for` took the first adapter whose globs hit, so a phone pack that
    also claims a car site held a car's quick look to the phone principle
    (B150). Every matching adapter reads the page; the fullest reading wins.
    """
    if not url:
        return ""
    from kriko.adapters import best_reading

    specs = sites.adapters_for(store, conn, url)
    found = best_reading(store, specs, facts, url=url, title=title) if specs else None
    if not found:
        return ""
    spec, mapped = found
    pack = spec.get("pack_id", "") or ""
    if len({one.get("pack_id", "") for one in specs}) > 1 and pack:
        # Several packs claim this site and the winner knows none of what it
        # read: every reading tied and the first one won. That held a car
        # listing's quick look to a phone pack's principle (B151); no pack's
        # principle is the honest answer for a product no pack knows.
        from kriko.adapters import _fold, identity_vocabulary

        own = {key: {_fold(v) for v in values}
               for key, values in identity_vocabulary(store, [pack]).items()}
        if not any(_fold(value) in own.get(key, ()) for key, value in mapped.identity.items()):
            return ""
    return pack


@router.post("/research-plane")
def start_research_plane(
    body: ExtensionResearchRequest, request: Request,
    store=Depends(get_store), runner=Depends(get_jobs),
    conn=Depends(get_app_state),
) -> dict:
    try:
        subject = resolve_research_subject(store, q=body.q, subject_id=body.subject_id)
    except HTTPException as exc:
        if exc.status_code != 404 or not body.allow_draft or not body.q.strip():
            raise
        from app import prefs
        from app.providers import apiagent, harness

        installed = harness.available()
        stored = (prefs.read(conn).get(prefs.HARNESS) or "") if conn is not None else ""
        requested = body.harness.strip()
        api_ids = {one.id for one in apiagent.available()}
        installed_ids = {one.id for one in installed}
        if requested and requested != prefs.LOCAL_PICK and requested not in api_ids | installed_ids:
            raise HTTPException(503, f"The selected research agent is not available: {requested}") from exc
        # An API agent counts only once picked: it bills per token, and a
        # key saved for something else is not a yes to that (B153).
        picked_api = (requested in api_ids) if requested else stored in api_ids
        # The model on this computer (B171, B172): first for a reader who has
        # picked no agent, and the only door for one who has none at all.
        from app import localplane

        local = localplane.resolve(
            getattr(request.app.state.settings, "app_state_path", None),
            with_search=False)
        # "local" is a pick of its own (the Agents tab's Local model row), not
        # an agent id, so it is never checked against the installed CLIs.
        wants_local = requested == prefs.LOCAL_PICK or (not requested and (
            not stored or stored == prefs.LOCAL_PICK or (not installed and not picked_api)))
        if not local["ready"] and (requested == prefs.LOCAL_PICK
                                   or (not requested and stored == prefs.LOCAL_PICK)):
            raise HTTPException(503, f"The local model is not ready. {local['reason']}") from exc
        if wants_local and local["ready"]:
            from app import pagefacts

            page = pagefacts.clean(body.facts, body.description)
            if not body.quick:
                deepen = runner.submit("pack_author", {
                    "category": body.q.strip(), "product": body.q.strip(),
                    "harness": "", "backend": "local", "install": True,
                    "page": page, "budget_usd": 0.0,
                })
                return {
                    "job_id": deepen, "kind": "pack_author", "backend": "local",
                    "harness": "", "cost_basis": "self_hosted", "budget_usd": 0.0,
                    "why": local["line"],
                    "note": "Runs on the local model and installs its product research when done.",
                }
            # One job, not two: a quick look is saved on its own and joins a
            # pack only when the reader asks (`POST /quick-looks/{id}/pack`).
            pack_id = _listing_pack(store, conn, body.url, body.facts, body.q.strip())
            quick = runner.submit("quick_look", {
                "product": body.q.strip(), "page_url": body.url, "harness": "", "backend": "local",
                "pack_id": pack_id, "page": page, "budget_usd": 0.0,
            })
            return {
                "job_id": quick, "kind": "quick_look",
                "backend": "local", "harness": "", "cost_basis": "self_hosted",
                "budget_usd": None, "why": local["line"],
                "note": f"Runs on {local['model']} on this computer: no key and "
                        "no subscription. It can be slow on a CPU. The quick look "
                        "is saved; add it to a pack when you want it kept as knowledge.",
            }
        if not installed_ids and not picked_api:
            raise HTTPException(503, (
                "Product drafts need an agent. Install a coding-agent CLI, pick "
                "the Mistral API agent in Settings → Agents (it needs a Mistral "
                "key), or run a local model server with a model downloaded. "
                + local["reason"] + " No API research was started."
            )) from exc
        # Decided once, here, and then both reported and obeyed.
        #
        # Passing `available[0].id` was passing it *explicitly*, and an
        # explicit harness beats the stored one — so the reader who chose
        # another agent precisely to stop spending Claude tokens got Claude
        # Code every time the extension researched a product, while this reply
        # named the choice it had just overridden. The order below is the fix
        # for that: the stored preference wins whenever it names something
        # actually installed.
        #
        # Leaving the *job* empty and letting `harness_researcher` work it out
        # again is not the fix, though — it is the same decision made twice
        # from two copies of one rule, so the reply can promise one agent while
        # the run uses another the day the two copies drift. Sending `selected`
        # is what this reply already claims happened.
        from app import pagefacts

        page = pagefacts.clean(body.facts, body.description)
        if requested:
            selected = requested
        elif picked_api or stored in installed_ids:
            selected = stored
        else:
            selected = installed[0].id
        billed = selected in apiagent.BY_ID
        # Each job carries its own ceiling, because each is a separate bill:
        # the quick look at this door's cap, the deeper draft at the agent's.
        quick_budget = EXTENSION_RESEARCH_BUDGET_USD if billed else 0.0
        deep_budget = apiagent.DEFAULT_BUDGET_USD if billed else 0.0
        params = {
            # The listing's own title is the product. Which category pack it
            # joins is decided by the run, from the installed packs (B169),
            # so the title is only the fallback name for a new one.
            "category": body.q.strip(), "product": body.q.strip(),
            "harness": selected, "backend": "harness",
            # The reader's answer, asked directly: "yes it should install
            # itslef" (B148). Only this door asks for it; the app's own New
            # pack form still leaves the press to the reader.
            "install": True,
            "page": page,
            "budget_usd": deep_budget,
        }
        # Quick answer, then deepen (B148): the reader's choice. The draft is
        # the deep half and starts first so the quick one can point at it;
        # the quick look runs in its own lane (`jobs.QUICK_KINDS`) and is the
        # id the panel follows.
        if not body.quick:
            deepen = runner.submit("pack_author", params)
            if billed:
                label = apiagent.BY_ID[selected].label
                return {
                    "job_id": deepen, "kind": "pack_author", "backend": "harness",
                    "harness": selected, "cost_basis": "per_token",
                    "budget_usd": deep_budget,
                    "note": f"Bills your {label} key: about ${deep_budget:.2f} for the product research.",
                }
            return {
                "job_id": deepen, "kind": "pack_author", "backend": "harness",
                "harness": selected, "cost_basis": "subscription", "budget_usd": None,
                "note": "Uses your harness subscription and installs its product research when done.",
            }
        pack_id = _listing_pack(store, conn, body.url, body.facts, body.q.strip())
        quick = runner.submit("quick_look", {
            "product": body.q.strip(), "page_url": body.url, "harness": selected,
            "pack_id": pack_id, "page": page, "budget_usd": quick_budget,
        })
        if billed:
            label = apiagent.BY_ID[selected].label
            return {
                "job_id": quick, "kind": "quick_look",
                "backend": "harness", "harness": selected,
                "cost_basis": "per_token",
                # "About": the ceiling refuses the next request once spent,
                # and the request in flight can finish a little past it.
                "budget_usd": round(quick_budget, 2),
                "note": f"Bills your {label} key: about ${quick_budget:.2f} for the "
                        "quick look. It is saved; add it to a pack when you want "
                        "it kept as knowledge.",
            }
        return {
            "job_id": quick, "kind": "quick_look",
            "backend": "harness", "harness": selected,
            "cost_basis": "subscription", "budget_usd": None,
            "note": "Uses your harness subscription. The quick look is saved; "
                    "add it to a pack when you want it kept as knowledge.",
        }
    plane = research_plane(request)
    budget = min(body.cap or EXTENSION_RESEARCH_BUDGET_USD,
                 EXTENSION_RESEARCH_BUDGET_USD)
    params = {
        **subject, "backend": plane["backend"],
        "model": body.model, "search": body.search,
        "budget_usd": budget if plane["cost_basis"] == "per_token" else 0.0,
    }
    return {
        "job_id": runner.submit("research", params), "kind": "research",
        **subject, **plane, "budget_usd": params["budget_usd"],
    }


@router.get("/quick-looks")
def saved_quick_look(url: str, product: str = "", conn=Depends(get_app_state)) -> dict:
    """Restore the newest successful result; a failed refresh cannot erase it."""
    from app.pageidentity import canonical_url

    wanted = canonical_url(url)
    if not wanted:
        return {"job": None}
    name = " ".join(product.casefold().split())
    for row in conn.execute(
        "SELECT * FROM jobs WHERE kind = 'quick_look' AND state = 'succeeded'"
        " ORDER BY created_at DESC, rowid DESC"
    ):
        job = state._job(row)
        params = job["params"]
        if canonical_url(params.get("page_url", "")) != wanted:
            continue
        if name and " ".join(str(params.get("product", "")).casefold().split()) != name:
            continue
        return {"job": job}
    return {"job": None}


@router.post("/quick-looks/{job_id}/pack")
def add_quick_look_to_pack(job_id: str, runner=Depends(get_jobs),
                           conn=Depends(get_app_state)) -> dict:
    """Make a saved quick look part of a pack.

    The reader's words: "Quick looks shouldn't be a pack but quick looks can
    be a part of a pack." A quick look is one saved job; this is the second,
    asked for: the product research run on the same agent the look used,
    which reads the look's sourced risks (`quick_job_id`) instead of searching
    for them again, files them into the category's pack and installs it.
    """
    job = state.get_job(conn, job_id) if conn is not None else None
    if not job or job["kind"] != "quick_look":
        raise HTTPException(404, f"no quick look {job_id}")
    if job["state"] != state.SUCCEEDED:
        raise HTTPException(409, "This quick look did not finish, so there is nothing to add yet.")
    # Pressed twice, it is one pack run: the one already going is the answer.
    for one in state.list_jobs(conn, 200):
        if (one["kind"] == "pack_author" and not one["done"]
                and one["params"].get("quick_job_id") == job_id):
            return {"job_id": one["job_id"], "kind": "pack_author", "quick_job_id": job_id,
                    "backend": one["params"].get("backend", ""),
                    "harness": one["params"].get("harness", "")}
    look = job["params"]
    product = str(look.get("product") or "").strip()
    local = str(look.get("backend") or "") == "local"
    from app.providers import apiagent

    harness = str(look.get("harness") or "")
    billed = harness in apiagent.BY_ID
    deepen = runner.submit("pack_author", {
        "category": product, "product": product,
        "harness": "" if local else harness,
        "backend": "local" if local else "harness",
        "install": True, "page": look.get("page") or {},
        "quick_job_id": job_id,
        "budget_usd": apiagent.DEFAULT_BUDGET_USD if billed else 0.0,
    })
    return {"job_id": deepen, "kind": "pack_author", "quick_job_id": job_id,
            "backend": "local" if local else "harness", "harness": harness}


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
    request.app.state.extension_staged_digest = extension.content_digest(target)
    return {
        "path": str(target), "written": written, "version": extension.version(target),
        "content_digest": extension.content_digest(target),
        "files": extension.content_files(target),
    }


@router.post("/firefox/stage")
def stage_firefox(request: Request) -> dict:
    source = extension.source_dir()
    if source is None:
        raise HTTPException(status_code=501, detail="This build does not carry the extension.")
    target = extension.target_for(request.app.state.settings.store_path, "firefox")
    try:
        extension.stage(source, target, "firefox")
        output = extension.package(target, target.with_suffix(".xpi"))
    except (OSError, ValueError) as cause:
        raise HTTPException(status_code=500, detail=f"Could not prepare the Firefox add-on: {cause}")
    request.app.state.firefox_staged_digest = extension.content_digest(target)
    return {"path": str(target), "version": extension.version(target), "package_path": str(output),
            "signed": False, "note": "Ready for Load Temporary Add-on in Firefox. A permanent install needs Mozilla signing."}


@router.post("/firefox/reveal")
def reveal_firefox(request: Request) -> dict:
    target = extension.target_for(request.app.state.settings.store_path, "firefox")
    manifest = target / "manifest.json"
    if not manifest.is_file():
        raise HTTPException(status_code=409, detail="Prepare the Firefox add-on first.")
    return {"path": str(manifest), "error": extension.reveal(manifest)}


@router.post("/reveal")
def reveal(request: Request, spawn: bool = True) -> dict:
    """Open the staged folder in the file manager.

    A convenience with a fallback, never a requirement: the response carries
    the path either way, because the reader's next action is pasting it.

    `spawn=false` only answers with the path. The desktop shell asks for that
    and opens the folder itself: a window opened by this background process
    is not the foreground one, so Windows leaves it behind the app and the
    button looks dead.
    """
    target = _target(request)
    if not target.is_dir():
        raise HTTPException(status_code=409, detail="nothing staged yet — add it first")
    return {"path": str(target), "error": extension.reveal(target) if spawn else ""}


def _landing(store, app_conn, base_url: str) -> str:
    """Where the launched browser should open.

    A site this installation can actually read, so the extension has
    something to do the moment the window appears. This used to be *this
    app's own* extension page, and the reader's report of it was exact: "it
    just opens the app interface in the web browser, an exact copy of the
    standalone app. I originally meant the hovering web extension." They were
    right — the one place the extension is invisible is a page it does not
    match.

    The site is read off `sites.registered`, never named here: which listing
    sites exist is pack data plus whatever this reader taught their own copy
    (`test_the_landing_page_is_pack_data`), and a reader whose only readable
    site is one they just registered locally deserves the same one-click
    landing as one who installed a pack that ships an adapter — a launch that
    only ever knew about pack sites would silently regress the moment
    `/api/sites/{host}/register` did its job. Superseded local rows are
    skipped: they duplicate a pack entry that is already in the list.
    With nothing readable at all there is no such page, and the app's own
    screen is the honest fallback — it is at least the screen that says what
    to do next.
    """
    for row in sites.registered(store, app_conn):
        if row.get("superseded"):
            continue
        site = str(row.get("site") or "").strip().strip("/")
        if site:
            return site if "://" in site else f"https://{site}/"
    return f"{base_url.rstrip('/')}/#/extension"


@router.post("/launch")
def launch(
    request: Request, store=Depends(get_store), app_state=Depends(get_app_state)
) -> dict:
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
    request.app.state.extension_staged_digest = extension.content_digest(target)

    home = extension.home_of(request.app.state.settings.store_path)
    profile = extension.profile_dir(home)
    note = (
        "The window is a separate browser profile — it has to be, because a "
        "browser that is already running ignores an extension handed to it on "
        "the command line. Your bookmarks and logins are not in it. Recent "
        "Chrome releases refuse to load an extension this way; if Status "
        "stays waiting, the steps below are the install."
    )

    browser = extension.find_chromium()
    if browser is None:
        return {
            "launched": False,
            "browser": "",
            "path": str(target),
            "profile": str(profile),
            "landing": "",
            "note": note,
            "error": (
                "No Chrome, Chromium, Brave or Edge found on this machine. "
                "Firefox cannot be handed an extension this way — the steps "
                "below are the install for it."
            ),
        }

    # A page the extension matches, not a second copy of this app — see
    # `_landing`. The confirmation the reader was previously sent to the
    # browser to see is on *this* screen too, and this screen is already in
    # front of them: the status card polls, so it turns green here while they
    # are looking at the listing over there.
    landing = _landing(store, app_state, str(request.base_url))
    # A browser that has checked in already has Kriko, loaded from `target`
    # and refreshed by the `stage` above — so the listing opens *there*. The
    # separate profile is only for a reader who has never installed it, and
    # current Chrome refuses to load an extension into it (see
    # `launch_with_extension`), which is why the manual steps stay on screen.
    own = bool(state.extension_sightings(app_state))
    if own:
        note = (
            "Opened in the browser Kriko already lives in — its files were "
            "refreshed just now, so the listing gets this version."
        )
    error = extension.launch_with_extension(
        browser, target, profile, landing=landing, own_profile=own
    )
    return {
        "launched": not error,
        "browser": browser,
        "path": str(target),
        "profile": "" if own else str(profile),
        "landing": landing,
        "note": note,
        "error": error,
    }
