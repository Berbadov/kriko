"""Asking the installed packs about a thing."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.web.deps import get_store
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
def run_lookup(body: LookupRequest, store=Depends(get_store)):
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
    return {
        "method": result.resolution.method,
        "coverage": result.coverage,
        "notes": result.resolution.notes,
        "flags": list(result.resolution.flags),
        "subjects": list(result.resolution.subject_ids),
        "claims": [
            {
                "claim_id": c.claim_id,
                "pack_id": c.pack_id,
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


@router.get("/identity-keys/{pack_id}")
def identity_keys(pack_id: str, store=Depends(get_store)):
    """Which attributes actually select a subject in this pack — the fields a
    search form should offer, read off the pack rather than hard-coded."""
    return [
        dict(r)
        for r in store.execute(
            "SELECT DISTINCT a.key, t.match_json FROM attributes a"
            " JOIN terms t ON t.term_id = a.key AND t.pack_id = a.pack_id"
            " WHERE a.pack_id = ? AND a.is_identity = 1 ORDER BY a.key",
            (pack_id,),
        )
    ]
