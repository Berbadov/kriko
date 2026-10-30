"""A researched product's saved check, made or refreshed on the engine.

The window used to build a product's identity itself and post it to
`/api/lookup`, which saved a new row every time. This door takes only the
product, reads its identity from the catalog, and keeps one saved check per
product (see `app/web/productchecks.py`).
"""

from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import audit, productinsights
from app.pageidentity import canonical_url
from app.web import productchecks
from app.web import state
from app.web.deps import get_app_state, get_store

router = APIRouter(prefix="/api/products", tags=["products"])


class ScanItem(BaseModel):
    name: str = Field(default="", max_length=400)
    url: str = Field(default="", max_length=2000)
    text: str = Field(default="", max_length=2000)
    fields: dict = Field(default_factory=dict, max_length=100)


class ScanRequest(BaseModel):
    items: list[ScanItem] = Field(max_length=60)


@router.post("/scan")
def scan_products(body: ScanRequest, app_state=Depends(get_app_state),
                  store=Depends(get_store)) -> dict:
    """Local catalog scans, without history writes, web requests or agents."""
    from app.web.routers.analyze import ScrapeRequest, answer

    items = []
    for item in body.items:
        name = item.name
        payload = None
        basis = "page text"
        lookup_id = ""
        if not name and canonical_url(item.url):
            # URL-only scans first use a saved page read; URL slugs alone are
            # never represented as a verified product identity.
            for row in app_state.execute("SELECT * FROM lookups ORDER BY created_at DESC LIMIT 1000"):
                saved = state._decode(row)
                if canonical_url(saved["request"].get("url", "")) == canonical_url(item.url):
                    payload = saved["response"]
                    name = saved["label"]
                    lookup_id = saved["lookup_id"]
                    basis = "saved page check"
                    break
        if payload is None:
            if not name and canonical_url(item.url):
                name = unquote(urlsplit(item.url).path.rsplit("/", 1)[-1]).replace("-", " ").replace("_", " ")
                basis = "URL words only; open the listing to confirm the product"
            payload, _, _ = answer(store, app_state, ScrapeRequest(
                # Result cards have a name, not the listing adapter's labelled
                # specification. Let the any-site name matcher read them.
                url=item.url if item.fields else "", title=name, product_name=name[:300], description=item.text,
                fields=item.fields, limit=50))
        claims = payload.get("claims") or []
        method = payload.get("method", "no_match")
        levels = [one.get("severity", "unrated") for one in claims]
        level = next((one for one in ("critical", "high", "medium", "low") if one in levels), "unknown")
        if method in ("ambiguous", "probable", "no_match") or basis.startswith("URL words"):
            level = "uncertain" if claims else "unknown"
        listing = audit.listing(url=item.url, title=name, description=item.text, fields=item.fields)
        items.append({"name": name, "url": item.url, "lookup_id": lookup_id, "basis": basis,
                      "level": level, "method": method, "coverage": payload.get("coverage", "UNKNOWN"),
                      "claims": claims, "audit": listing,
                      "freshness": productinsights.freshness(store, claims),
                      "costs": productinsights.costs(claims)})
    return {"items": items}


@router.get("/checks/{lookup_id}/insights")
def check_insights(lookup_id: str, days: int = Query(30, ge=1, le=3650),
                   app_state=Depends(get_app_state), store=Depends(get_store)) -> dict:
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, "No saved check")
    claims = row["response"].get("claims") or []
    subjects = row["response"].get("subjects") or []
    subject = subjects[0] if len(subjects) == 1 else None
    subject_id = subject if isinstance(subject, str) else (subject or {}).get("subject_id", "")
    target = productchecks.enabled_subject(store, subject_id) if subject_id else None
    return {"freshness": productinsights.freshness(store, claims, days=days),
            "costs": productinsights.costs(claims), "target": target}


@router.get("/checks/{lookup_id}/report")
def export_report(lookup_id: str, days: int = Query(30, ge=1, le=3650),
                  app_state=Depends(get_app_state), store=Depends(get_store)):
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, "No saved check")
    claims = row["response"].get("claims") or []
    return HTMLResponse(productinsights.report(row, productinsights.freshness(store, claims, days=days),
                                              productinsights.costs(claims)), headers={
        "Content-Disposition": f'attachment; filename="kriko-{row["lookup_id"]}.html"',
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/checks/{lookup_id}/report-data")
def export_report_data(lookup_id: str, days: int = Query(30, ge=1, le=3650),
                       app_state=Depends(get_app_state), store=Depends(get_store)) -> dict:
    """Same artifact over the desktop shell's JSON transport."""
    row = state.get_lookup(app_state, lookup_id)
    if row is None:
        raise HTTPException(404, "No saved check")
    claims = row["response"].get("claims") or []
    return {"filename": f'kriko-{row["lookup_id"]}.html',
            "html": productinsights.report(row, productinsights.freshness(store, claims, days=days),
                                            productinsights.costs(claims))}


@router.post("/{subject_id}/check")
def check_product(subject_id: str, app_state=Depends(get_app_state),
                  store=Depends(get_store)) -> dict:
    try:
        return productchecks.ensure_check(app_state, store, subject_id)
    except productchecks.ProductNotFound as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
