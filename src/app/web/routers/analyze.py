"""The browser plane: a scraped page in, ranked claims out.

This is the drop-in replacement for the old `/analyze`, with one difference
that matters: the old endpoint knew about Sahibinden. This one knows about
adapters, and the cars pack knows about Sahibinden. Adding a listing site is a
JSON file in a pack.
"""

import logging
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app import matching, operations, sites
from app.web import state
from app.web.deps import get_app_state, get_store
from app.web.routers.history import label_for
from app.web.observability import log_analysis_jsonl
from kriko.adapters import (
    adapt,
    declared_labels,
    identity_vocabulary,
    load_adapters,
    local_panel,
)
from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.store import packstore

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analyze"])


class ScrapeRequest(BaseModel):
    url: str
    #: Raw label -> value pairs, exactly as they appear on the page. The
    #: extension does not interpret them; that is the adapter's job.
    fields: dict = Field(default_factory=dict)
    title: str = ""
    description: str = ""
    lang: str = "en"
    limit: int = 8
    #: Which door this came in by. A closed vocabulary is safe here where a
    #: hardcoded make/model would not be: doors are a fixed property of the
    #: system, not data that grows with pack coverage.
    origin: Literal["app", "extension"] = "app"


#: History rows predate `origin` and say "analyze" for an in-app run; renaming
#: them would only rewrite the past to look like the present.
_SOURCE_FOR_ORIGIN = {"app": "analyze", "extension": "extension"}


@router.get("/adapters")
def list_adapters(store=Depends(get_store), app_state=Depends(get_app_state)):
    """Which sites the installed packs can read, and what they match on.

    The extension uses this to know where it is worth scraping at all, and —
    since the pack's own version rides here — whether an answer it cached
    against an earlier version of that pack is worth trusting (extension-3,
    B145 audit): a stored answer keyed on the scrape alone can't tell a pack
    update happened, and kept serving the pre-update claims for hours.
    """
    pack_versions = {row["pack_id"]: row["version"] for row in packstore.installed_packs(store)}
    return [
        {
            "id": a.get("id"),
            "site": a.get("site"),
            "pack_id": a["pack_id"],
            "version": pack_versions.get(a["pack_id"], ""),
            "match": a.get("match", []),
            "labels": declared_labels(a),
            # The panel the extension draws over the reader's own page. It
            # rides with the adapter because it is the same kind of thing —
            # site knowledge the browser interprets and never invents. An
            # adapter that declares none gets an empty block and the panel
            # renders nothing local, which is the honest result.
            "local_panel": local_panel(a),
        }
        for a in load_adapters(store)
    ] + [
        # Sites this installation learned by itself. Listed here because this
        # endpoint is what the extension reads to decide where to inject: a
        # site the reader registered is useless if the browser never runs on
        # it, and that seam is exactly what "it only opens on sahibinden" was.
        {
            "id": (row.get("spec") or {}).get("id", f"local.{row['host']}"),
            "site": row["host"],
            "pack_id": row.get("pack_id", ""),
            "match": (row.get("spec") or {}).get("match", []),
            "labels": declared_labels(row.get("spec") or {}),
            "local_panel": local_panel(row.get("spec") or {}),
            "local": True,
        }
        for row in sites.local_rows(app_state)
    ]


@router.get("/adapters/unmapped")
def unmapped(
    limit: int = 100, adapter_id: str = "", app_state=Depends(get_app_state)
):
    """Labels the pages carried that no installed adapter reads.

    The whole point of persisting them: this list is where "the site renamed a
    field last Tuesday" is legible. A label with a high `seen` and a recent
    `last_at` on a site that used to work is a markup change; one seen twice in
    June is noise an author can dismiss.

    Deliberately not derived from `declared_labels` — a label absent from the
    adapter is not interesting, a label *present on the page* and absent from
    the adapter is. Only the reader's actual browsing can tell the difference.
    """
    return {"labels": state.unmapped_labels(app_state, limit, adapter_id=adapter_id)}


@router.delete("/adapters/unmapped/{adapter_id}/{label:path}")
def forget_unmapped(adapter_id: str, label: str, app_state=Depends(get_app_state)):
    """Dismiss one label.

    A list that cannot be pruned stops being read, and some labels are never
    going to be mapped. Not permanent: the next listing carrying the label puts
    it back, which is the honest answer to "I dismissed this and it is still
    happening".
    """
    return {"forgotten": state.forget_unmapped(app_state, adapter_id, label)}


def _context_units(store, context) -> dict:
    """The unit each context key is measured in, as the packs declared it.

    The panel needs this to render a number a reader can act on, and asking it
    to know that `usage_km` is kilometres would be the hardcoded-list bug in
    JavaScript — right until a pack measures wear in charge cycles.
    """
    if not context:
        return {}
    placeholders = ",".join("?" * len(context))
    rows = store.execute(
        f"SELECT term_id, unit FROM terms WHERE term_id IN ({placeholders})"
        " AND unit != ''",
        list(context),
    )
    return {r["term_id"]: r["unit"] for r in rows}


def _resolved(store, subject_ids) -> list[dict]:
    """The subjects a lookup landed on, with how much is known about each.

    Enabled packs only, matching every other read: a disabled pack's subject
    must not appear as somewhere to send a research run.

    The claim count is the point of the row. Zero is the actionable value —
    the listing matched something the installed packs recognise and have
    nothing to say about — and a caller that had to infer it from an empty
    `claims` array could not tell it apart from "nothing matched at all".
    """
    ids = tuple(dict.fromkeys(subject_ids))
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [
        dict(row)
        for row in store.execute(
            f"SELECT s.subject_id, s.pack_id, s.label, s.kind,"
            f"       (SELECT COUNT(*) FROM claims c"
            f"        WHERE c.subject_id = s.subject_id"
            f"          AND c.pack_id = s.pack_id) AS claims"
            f" FROM subjects s JOIN packs p USING (pack_id)"
            f" WHERE p.enabled = 1 AND s.subject_id IN ({marks})"
            f" ORDER BY s.label",
            ids,
        )
    ]


def _packs_behind(store, claims) -> list[dict]:
    ids = sorted({c.pack_id for c in claims})
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = store.execute(
        f"SELECT pack_id, version FROM packs WHERE pack_id IN ({placeholders})"
        " ORDER BY pack_id",
        ids,
    )
    return [{"pack_id": r["pack_id"], "version": r["version"]} for r in rows]


def _record_analysis(request, app_state, body, mapped, result) -> None:
    """One row in the operations feed for one analysis. Never raises.

    Takes the endpoint's own `app_state` connection (B145 apicode-2) rather
    than a path: this runs on every analysis, and a second connect-plus-
    two-commits on top of the one the handler already opened was costing more
    than the lookup it was recording.
    """
    try:
        with operations.record(
            conn=app_state,
            door="extension" if body.origin == "extension" else "app",
            kind="lookup",
            name="analyze",
            arguments={"url": body.url, "identity": mapped.identity},
        ) as outcome:
            outcome["response"] = operations.summarise(
                {
                    "subjects": list(result.resolution.subject_ids),
                    "claims": len(result.claims),
                    "coverage": result.coverage,
                    "method": result.resolution.method,
                }
            )
    except Exception:  # noqa: BLE001 — see the call site
        pass


@router.post("/analyze")
def analyze(
    request: Request,
    body: ScrapeRequest,
    store=Depends(get_store),
    app_state=Depends(get_app_state),
):
    # The packs' adapters first, then whatever this installation has learned
    # about a site nobody shipped one for (`app/sites.py`). The order is the
    # design: a published adapter always wins over a local guess.
    spec = sites.adapter_for(store, app_state, body.url)
    if spec is None:
        # Not a 404 (check-21): a listing site nothing reads is an expected,
        # frequent answer — the reader's first paste is as likely to be a
        # site with no adapter as one with — and raising for it meant every
        # normal case of this logged a console error the same as a dead
        # server would. `readable_sites` lets the client name what does work
        # by its title instead of a bare `pack_id`.
        return {
            "readable": False,
            "reason": "no_adapter",
            "readable_sites": [
                {"site": a["site"], "pack_id": a["pack_id"]}
                for a in list_adapters(store, app_state)
            ],
        }

    # The vocabulary is the packs' own identity rows. It is what lets the
    # adapter read an identity value straight out of a page title when the
    # page has no label for it, without a single value being written down in
    # either the engine or the adapter JSON.
    mapped = adapt(
        spec,
        body.fields,
        url=body.url,
        title=body.title,
        description=body.description,
        vocabulary=identity_vocabulary(store),
    )

    # An adapter matching the URL is not the same as the page having been
    # read: the extension sends fields scraped from the DOM, but a bare URL
    # (typed or pasted into Check) has none, so `adapt` has nothing to map
    # and `mapped.identity` comes back empty. Running the lookup anyway asks
    # "what is known about no product in particular" and gets back
    # `no_match` — which reads, wrongly, as "no pack covers this kind of
    # product at all". This is a distinct, expected outcome, so it is
    # reported as one rather than run through the lookup and recorded to
    # history as an empty check.
    if not body.fields and not mapped.identity:
        return {
            "readable": False,
            "reason": "page_not_read",
            "adapter": mapped.adapter_id,
            "next_step": (
                "Kriko cannot open listing pages by itself. Open this ad "
                "with the browser extension, or describe it by hand."
            ),
        }

    result = lookup(
        store,
        Query(
            kind=mapped.kind,
            identity=mapped.identity,
            context=mapped.context,
            lang=body.lang,
            limit=body.limit,
        ),
    )

    payload = {
        "adapter": mapped.adapter_id,
        # Whose knowledge this is. With several packs installed and no central
        # authority deciding between them, the byline is not a detail — it is
        # how a reader tells a manufacturer bulletin from a forum consensus,
        # and how they know which pack to disable when one is wrong.
        "packs": _packs_behind(store, result.claims),
        "context_units": _context_units(store, mapped.context),
        "identity": mapped.identity,
        "context": mapped.context,
        # Labels the page had that no adapter rule covers. Not an error — a
        # coverage signal, so a site adding a useful field is discoverable
        # rather than silently ignored forever.
        "unmapped_labels": list(mapped.unmapped),
        "method": result.resolution.method,
        "coverage": result.coverage,
        "flags": list(result.resolution.flags),
        # How sure, and of what. A client that renders `PROBABLE_MATCH` as a
        # match is showing a guess as a fact, and one that renders it as
        # nothing is back at the dead end — so the doubt travels with the
        # answer rather than being inferred from it.
        **matching.scoring(result.resolution),
        "next_step": matching.next_step(result.resolution, result.coverage,
                                        body.url),
        # Which subjects the listing actually resolved to, claims or not.
        # `claims` cannot answer this: the interesting case is a subject that
        # resolved and has nothing known about it, which is exactly the row
        # with no claim to carry it. It is what lets a caller offer "research
        # this" on a gap instead of only "here is what we know".
        "subjects": _resolved(store, result.resolution.subject_ids),
        "claims": [
            {
                # The claim's own identity, so a caller can refer back to it —
                # mark it, ask for it again, link to it. Without this the
                # panel could only ever describe a claim, never point at one.
                "claim_id": c.claim_id,
                "subject_id": c.subject_id,
                "title": c.title,
                "body": c.body,
                "advice": c.advice,
                "severity": c.severity,
                "domain": c.domain,
                "subject": c.subject_label,
                "relevance": round(c.relevance, 4),
                "disputed": c.disputed,
                "pack_id": c.pack_id,
                "why": list(c.why),
                "sources": [
                    {
                        "url": s.url,
                        "domain": s.domain,
                        "quote": s.quote,
                        "stance": s.stance,
                        "tier": s.tier,
                    }
                    for s in c.sources
                ],
            }
            for c in result.claims
        ],
    }

    # ── the one signal that a site changed its markup ────────────────────
    #
    # `mapped.unmapped` was computed on every lookup and dropped on every
    # lookup. When a listing site renames a field, nothing errors: the lookup
    # succeeds, resolves less precisely and returns fewer claims, so the
    # failure arrives as knowledge quietly going missing — indistinguishable
    # from a thin pack. The label was in the response the whole time.
    #
    # Guarded and after the payload, like the log below: a coverage signal is
    # never worth the reader's answer.
    try:
        state.record_unmapped(
            app_state, mapped.adapter_id, mapped.unmapped, url=body.url
        )
    except Exception:
        log.warning("could not record unmapped labels", exc_info=True)

    # Best-effort, and deliberately after the answer is assembled: a failure to
    # write the log must never cost the reader their result. This log is where
    # the demand signal and the next parity corpus come from.
    log_analysis_jsonl(
        {
            "url": body.url,
            "adapter": mapped.adapter_id,
            "identity": mapped.identity,
            "context": mapped.context,
            "unmapped_labels": list(mapped.unmapped),
            "method": result.resolution.method,
            "coverage": result.coverage,
            "flags": list(result.resolution.flags),
            "subjects": list(result.resolution.subject_ids),
            "claim_titles": [c.title for c in result.claims],
        },
        path=request.app.state.settings.analysis_log_path,
    )

    # The JSONL log above and this row are different artifacts on purpose: the
    # log is the parity corpus and the demand signal, this is the reader's
    # history. Collapsing them would make clearing your history delete
    # research data.
    # And the feed (B122). An analysis is an operation too — it is the one the
    # reader's browser makes, so a feed that showed only agent work would go
    # silent exactly while the product is being used. Written after the answer
    # rather than around it: the work is a local lookup measured in
    # milliseconds, so a `running` row would never be seen, and a recorder that
    # can raise must not stand between a page and its claims.
    _record_analysis(request, app_state, body, mapped, result)

    payload["lookup_id"] = state.record_lookup(
        app_state,
        source=_SOURCE_FOR_ORIGIN[body.origin],
        label=_analyze_label(store, body, mapped, result),
        request=body.model_dump(),
        response=payload,
    )
    # The Result heading and "Open the listing" link both need the URL by
    # itself, not folded into a label string (check-15).
    payload["url"] = body.url
    return payload


def _analyze_label(store, body: ScrapeRequest, mapped, result) -> str:
    """A short title, not the raw 150-character URL (check-15).

    A page's own <title> (`body.title`) is usually a listing site's own
    boilerplate, not a product name, so it is preferred only when the
    adapter found nothing to identify the product by. When it did, that
    identity is the readable name; otherwise this falls back to naming the
    site the listing came from, which is still shorter and more honest than
    printing the address itself.

    As in query.py's `_history_label`, the label is read straight off the
    matched subject's own row rather than off a claim: ranking can surface
    claims written against a related subject, so the matched subject need
    not own any claim of its own.
    """
    if result.resolution.method in ("exact", "identity") and result.resolution.subject_ids:
        row = store.execute(
            "SELECT label FROM subjects WHERE subject_id = ?",
            (result.resolution.subject_ids[0],),
        ).fetchone()
        if row and row["label"]:
            return row["label"]
    if mapped.identity:
        return label_for(mapped.identity)
    host = urlparse(body.url).netloc.removeprefix("www.") or body.url
    return f"Listing on {host}"


@router.post("/diagnose/identity")
def diagnose_identity(
    body: ScrapeRequest,
    store=Depends(get_store),
    app_state=Depends(get_app_state),
):
    """Why this page matched what it matched — or why it matched nothing.

    The reader's ask, in their words: *"I need to be able to debug this myself
    without reading source."* So this is the whole chain in one object — the
    adapter that claimed the page, the identity it read off it, the labels it
    could not place, every subject weighed, each key's score, and the
    threshold the winner cleared or missed.

    Deliberately a second door onto the *same* call rather than a mode on
    `/analyze`. A diagnostic that changes the thing it measures is worthless,
    and the reader's answer must not carry a debugging payload: this returns
    the trace and no claims, `/analyze` returns claims and the summary, and
    both run the identical adapt-then-lookup path.

    It records no history and writes no analysis log. Looking at why something
    failed is not the same act as asking about a product, and a diagnostic that
    filled the reader's history with attempts would make the history useless
    exactly when they needed it.
    """
    spec = sites.adapter_for(store, app_state, body.url)
    if spec is None:
        # Not a 404. "Nothing here reads this site" is the single most common
        # answer this endpoint has, and it is a *finding* — the one that
        # explains a silent panel — so it comes back as one rather than as an
        # error the client has to catch to display.
        return {
            "adapter": None,
            "page": {"url": body.url},
            "outcome": {
                "method": "no_adapter",
                "verdict": "unreadable",
                "notes": f"no installed pack, and nothing this installation has "
                         f"learned, reads {sites.host_of(body.url) or body.url}",
            },
            "considered": [],
            "next_step": {
                "action": "register_site",
                "say": "Kriko cannot read this site yet. Add it on the Sites "
                       "screen and an agent will work out how.",
                "url": body.url,
            },
        }

    mapped = adapt(
        spec,
        body.fields,
        url=body.url,
        title=body.title,
        description=body.description,
        vocabulary=identity_vocabulary(store),
    )
    result = lookup(
        store,
        Query(kind=mapped.kind, identity=mapped.identity,
              context=mapped.context, lang=body.lang, limit=body.limit),
    )
    out = matching.diagnosis(mapped, result, spec)
    out["next_step"] = matching.next_step(result.resolution, result.coverage,
                                          body.url)
    # Not the claims themselves — how many there would be. Someone debugging a
    # match wants to know the answer was non-empty, not to read it here.
    out["outcome"]["claims"] = len(result.claims)
    return out
