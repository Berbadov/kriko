"""Asking the installed packs about a thing."""

import json

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.web import state
from app.web.deps import get_app_state, get_store
from app.web.routers.analyze import _context_units
from app.web.routers.history import label_for
from kriko.lookup import lookup
from kriko.lookup.query import Query

router = APIRouter(prefix="/api", tags=["query"])


class LookupRequest(BaseModel):
    kind: str = "product"
    #: What the thing IS — brand, model, engine code.
    identity: dict = Field(default_factory=dict)
    #: What this one has BEEN THROUGH — mileage, hours, cycles, age, ad text.
    context: dict = Field(default_factory=dict)
    lang: str = "en"
    limit: int = 8


@router.post("/lookup")
def run_lookup(
    body: LookupRequest,
    store=Depends(get_store),
    app_state=Depends(get_app_state),
):
    result = lookup(
        store,
        Query(
            kind=body.kind,
            identity=body.identity,
            context=body.context,
            lang=body.lang,
            limit=body.limit,
        ),
    )
    payload = {
        "method": result.resolution.method,
        "coverage": result.coverage,
        "notes": result.resolution.notes,
        "flags": list(result.resolution.flags),
        # Echoed for the same reason `/api/analyze` echoes it (check-13):
        # Report only renders its "Answered for …" strip when `context` is
        # present, and the mechanic hand-over needs the mileage/age too.
        "context": body.context,
        "context_units": _context_units(store, body.context),
        "subjects": list(result.resolution.subject_ids),
        "claims": [
            {
                "claim_id": c.claim_id,
                "pack_id": c.pack_id,
                # The subject the claim was written against, not only its
                # label. A reader marking a claim from the report has to be
                # able to say *which* subject was matched — that is the half
                # of a `not mine` verdict that names the failing system.
                "subject_id": c.subject_id,
                "title": c.title,
                "body": c.body,
                "advice": c.advice,
                "severity": c.severity,
                "domain": c.domain,
                "subject": c.subject_label,
                "detection": c.detection,
                "relevance": round(c.relevance, 4),
                "trust": round(c.trust, 3),
                "disputed": c.disputed,
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

    # Recorded after the answer is assembled, so a history write cannot cost
    # the reader their result — the same order the analysis log uses.
    payload["lookup_id"] = state.record_lookup(
        app_state,
        source="ask",
        label=_history_label(store, body, result, payload),
        request=body.model_dump(),
        response=payload,
    )
    return payload


def _history_label(store, body: LookupRequest, result, payload: dict) -> str:
    """The name a history row and a Compare column show (check-14).

    `label_for` joins whatever identity values were sent, in whatever order
    the form happened to collect them — alphabetical by key, since a form
    has no other order to pick from — which reads as value soup ("1395
    EA211 petrol volkswagen golf 125 dq200") rather than a product's name.
    When the match resolved to exactly one subject, its own label (the one
    a claim card already shows under "subject") is the readable name; a
    context value is appended so two runs of the same product — different
    mileage, say — are not indistinguishable in History or Compare.

    The resolved subject's label is read straight from the store rather
    than off a claim: ranking can surface claims written against a related
    subject (a shared part, a sibling code), so the matched subject need
    not own any claim of its own, let alone the first one back.
    """
    label = label_for(body.identity)
    if result.resolution.method in ("exact", "identity") and len(result.resolution.subject_ids) == 1:
        row = store.execute(
            "SELECT label FROM subjects WHERE subject_id = ?",
            (result.resolution.subject_ids[0],),
        ).fetchone()
        if row and row["label"]:
            label = row["label"]
    context_bits = [
        f"{v} {payload['context_units'][k]}".strip()
        for k, v in (body.context or {}).items()
        if str(v).strip() and payload.get("context_units", {}).get(k)
    ]
    if context_bits:
        label = f"{label} · {', '.join(context_bits)}"
    return label


@router.get("/kinds")
def subject_kinds(store=Depends(get_store)):
    """Which kinds of thing the installed packs can answer about."""
    return [
        dict(r)
        for r in store.execute(
            "SELECT s.kind, s.pack_id, COUNT(*) AS n FROM subjects s"
            " JOIN packs p USING (pack_id) WHERE p.enabled = 1"
            " GROUP BY s.kind, s.pack_id ORDER BY n DESC"
        )
    ]


def _is_required(match_json: str | None) -> bool:
    """`match_json` is YAML, written by the builder — the same shape
    `kriko.lookup.match._match_rules` parses for the engine's own use. The
    form was reading it with `JSON.parse`, which throws on YAML and silently
    turned every required key into an optional one (check-2); parse it once,
    here, and hand the client a plain bool instead of a format to guess at."""
    if not match_json:
        return False
    try:
        parsed = yaml.safe_load(match_json)
    except yaml.YAMLError:
        try:
            parsed = json.loads(match_json)
        except json.JSONDecodeError:
            return False
    return bool(isinstance(parsed, dict) and parsed.get("required"))


@router.get("/identity-keys/{pack_id}")
def identity_keys(pack_id: str, store=Depends(get_store)):
    """Which attributes actually select a subject in this pack — the fields a
    search form should offer, read off the pack rather than hard-coded."""
    return [
        {"key": r["key"], "match_json": r["match_json"], "required": _is_required(r["match_json"])}
        for r in store.execute(
            "SELECT DISTINCT a.key, t.match_json FROM attributes a"
            " JOIN terms t ON t.term_id = a.key AND t.pack_id = a.pack_id"
            " WHERE a.pack_id = ? AND a.is_identity = 1 ORDER BY a.key",
            (pack_id,),
        )
    ]
