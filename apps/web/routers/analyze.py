"""The browser plane: a scraped page in, ranked claims out.

This is the drop-in replacement for the old `/analyze`, with one difference
that matters: the old endpoint knew about Sahibinden. This one knows about
adapters, and the cars pack knows about Sahibinden. Adding a listing site is a
JSON file in a pack.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.web.deps import get_store
from apps.web.observability import log_analysis_jsonl
from kriko.adapters import adapt, adapter_for, load_adapters
from kriko.lookup import lookup
from kriko.lookup.query import Query

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


@router.get("/adapters")
def list_adapters(store=Depends(get_store)):
    """Which sites the installed packs can read, and what they match on.

    The extension uses this to know where it is worth scraping at all.
    """
    return [{"id": a.get("id"), "site": a.get("site"), "pack_id": a["pack_id"],
             "match": a.get("match", [])} for a in load_adapters(store)]


@router.post("/analyze")
def analyze(body: ScrapeRequest, store=Depends(get_store)):
    spec = adapter_for(store, body.url)
    if spec is None:
        raise HTTPException(
            404, f"no installed pack has an adapter for {body.url}")

    mapped = adapt(spec, body.fields, url=body.url, title=body.title,
                   description=body.description)
    result = lookup(store, Query(kind=mapped.kind, identity=mapped.identity,
                                 context=mapped.context, lang=body.lang,
                                 limit=body.limit))

    payload = {
        "adapter": mapped.adapter_id,
        "identity": mapped.identity,
        "context": mapped.context,
        # Labels the page had that no adapter rule covers. Not an error — a
        # coverage signal, so a site adding a useful field is discoverable
        # rather than silently ignored forever.
        "unmapped_labels": list(mapped.unmapped),
        "method": result.resolution.method,
        "coverage": result.coverage,
        "flags": list(result.resolution.flags),
        "claims": [{
            "title": c.title, "body": c.body, "advice": c.advice,
            "severity": c.severity, "domain": c.domain,
            "subject": c.subject_label, "relevance": round(c.relevance, 4),
            "disputed": c.disputed, "pack_id": c.pack_id, "why": list(c.why),
            "sources": [{"url": s.url, "domain": s.domain, "quote": s.quote,
                         "stance": s.stance, "tier": s.tier} for s in c.sources],
        } for c in result.claims],
    }

    # Best-effort, and deliberately after the answer is assembled: a failure to
    # write the log must never cost the reader their result. This log is where
    # the demand signal and the next parity corpus come from.
    log_analysis_jsonl({
        "url": body.url, "adapter": mapped.adapter_id,
        "identity": mapped.identity, "context": mapped.context,
        "unmapped_labels": list(mapped.unmapped),
        "method": result.resolution.method, "coverage": result.coverage,
        "flags": list(result.resolution.flags),
        "subjects": list(result.resolution.subject_ids),
        "claim_titles": [c.title for c in result.claims],
    })
    return payload
