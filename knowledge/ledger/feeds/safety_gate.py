"""EU Safety Gate (formerly RAPEX) recalls feed -> structured documents + evidence.

Data source (validated 2026-08-02): the official weekly-report XML —
  https://ec.europa.eu/safety-gate-alerts/api/download/weeklyReport/list/xml/en
The previously reverse-engineered JSON search API (`/safety-gate/api/v2/alerts`)
is gone (404); there is no public JSON search endpoint left. The weekly index
lists one detail XML per week; each detail lists that week's alerts with brand,
product, danger, measures, caseNumber and an alert-detail URL.

Attribution design (mirrors nhtsa.py semantics):
- body/electrical-class alerts get target_hint = model's *_body/*_elec part
- powertrain alerts get target_hint="" -- resolve ONLY when the alert text
  names a discriminative catalog code (alias path)

Known gap: EU Safety Gate is EU-wide -- covers both VW and Renault. This
complements NHTSA (VW-only US). The TR SGM feed (feeds/recalls_tr.py) is
BLOCKED: sanayi.gov.tr answers non-browser clients with an anti-bot JS
challenge (TSPD), so its reverse-engineered JSON endpoint no longer returns
data to a server-side client.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from knowledge.ledger import db
from knowledge.ledger.feeds import (VARIANTS_DIR, catalog_models,
                                    model_part_hint as _model_part_hint)

log = logging.getLogger(__name__)

INDEX_URL = "https://ec.europa.eu/safety-gate-alerts/api/download/weeklyReport/list/xml/en"

FEEDS_EXTRACTOR_VERSION = 101

# 3 years of weekly reports. Recalls are old-car-relevant; raise this to
# backfill deeper history (the ledger dedups by document text hash, so an
# enlarged window re-runs cleanly).
MAX_WEEKS = 156
_FETCH_DELAY_S = 0.25  # be polite to the EU portal between detail fetches

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
}

_CATEGORY_MAP = {
    "motor vehicle": ("general", "alias"),
    "vehicle": ("general", "alias"),
    "car": ("general", "alias"),
    "engine": ("engine", "alias"),
    "transmission": ("transmission", "alias"),
    "gearbox": ("transmission", "alias"),
    "brake": ("brakes", "body"),
    "airbag": ("body", "body"),
    "electrical": ("electrical", "elec"),
    "steering": ("suspension", "body"),
    "suspension": ("suspension", "body"),
    "fuel": ("fuel system", "alias"),
    "fire": ("general", "body"),
    "seat": ("body", "body"),
    "lighting": ("electrical", "body"),
    "tyre": ("suspension", "body"),
    "tire": ("suspension", "body"),
}


def _classify(text: str) -> tuple[str, str]:
    """Safety Gate category/description -> (claim domain, routing class)."""
    text_lower = (text or "").lower()
    for keyword, (domain, route) in sorted(
            _CATEGORY_MAP.items(), key=lambda kv: -len(kv[0])):
        if keyword in text_lower:
            return domain, route
    return "general", "body"


@lru_cache(maxsize=64)
def _http_get_bytes(url: str) -> bytes:
    import httpx
    resp = httpx.get(url, timeout=30, follow_redirects=True, headers=_UA)
    resp.raise_for_status()
    return resp.content


def _cdata(notif: ET.Element, tag: str) -> str:
    el = notif.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _parse_weekly_alerts(xml_bytes: bytes) -> list[dict]:
    """Parse one weekly-report detail XML into alert dicts (brand-filterable)."""
    root = ET.fromstring(xml_bytes)
    alerts = []
    for notif in root.iter("notifications"):
        product = _cdata(notif, "product") or _cdata(notif, "name")
        danger = _cdata(notif, "danger")
        alerts.append({
            "title": product,
            "description": danger,
            "category": _cdata(notif, "category") or "motor vehicle",
            "url": _cdata(notif, "reference"),
            "referenceNumber": _cdata(notif, "caseNumber"),
            "brand": _cdata(notif, "brand"),
            "measures": _cdata(notif, "measures"),
        })
    return alerts


def _weekly_report_urls(getter, max_weeks: int) -> list[str]:
    """Newest-first detail-XML URLs from the weekly index (at most max_weeks)."""
    index = getter(INDEX_URL)
    root = ET.fromstring(index)
    urls = []
    for wr in root.findall("weeklyReport"):
        u = wr.findtext("URL") or ""
        if u:
            urls.append(u.replace("&amp;", "&"))
    return urls[:max_weeks]


def fetch_alerts(make: str, model: str, *, getter=_http_get_bytes,
                 max_weeks: int = MAX_WEEKS, delay: float = _FETCH_DELAY_S) -> list[dict]:
    """Alerts whose brand matches `make`, from the last max_weeks weekly reports.

    Brand-level (not model-level) filtering: Safety Gate entries often name
    only the brand (e.g. "Renault Megane" vs "Passenger car"), and document
    dedup in the ledger makes cross-model re-ingestion of the same alert a
    no-op. Model scoping happens later at resolve time via target_hint/alias.
    A week whose detail XML fails to parse is logged and skipped — one broken
    week must not kill the feed.
    """
    brand = make.lower()
    out: list[dict] = []
    for url in _weekly_report_urls(getter, max_weeks):
        try:
            alerts = _parse_weekly_alerts(getter(url))
        except Exception as exc:
            log.warning("Safety Gate week parse failed (%s): %s", url, exc)
            continue
        for a in alerts:
            if (a.get("brand") or "").lower().startswith(brand):
                out.append(a)
        if delay:
            time.sleep(delay)
    return out



def _doc_text(alert: dict) -> str:
    title = alert.get("title", "")
    desc = alert.get("description", "")
    text = f"{title}. {desc}" if desc else title
    measures = alert.get("measures", "")
    return f"{text} Measures: {measures}" if measures else text


def ingest_alerts(conn, make: str, model_key: str, *,
                 getter=_http_get_bytes) -> dict:
    """Ingest Safety Gate alerts for one catalog model. Idempotent."""
    summary = {"alerts": 0, "ingested": 0, "duplicates": 0, "errors": 0}
    try:
        alerts = fetch_alerts(make, model_key, getter=getter)
    except Exception as exc:
        log.warning("Safety Gate fetch failed for %s %s: %s", make, model_key, exc)
        summary["errors"] += 1
        return summary

    seen_urls: set[str] = set()
    for alert in alerts:
        summary["alerts"] += 1
        alert_url = alert.get("url") or f"safety-gate:{alert.get('referenceNumber', alert.get('title', ''))[:60]}"
        if alert_url in seen_urls:
            summary["duplicates"] += 1
            continue
        seen_urls.add(alert_url)

        title_text = alert.get("title", "")
        desc_text = alert.get("description", "")
        combined = f"{title_text} {desc_text}"
        domain, route = _classify(combined)
        hint = _model_part_hint(make, model_key, route)
        text = _doc_text(alert)

        doc_id = db.insert_document(
            conn, url=alert_url, source_type="structured",
            raw_text=text, site_or_channel="EU Safety Gate", target_hint=hint)

        title = f"Safety Gate: {title_text[:80]}"
        if conn.execute(
                "SELECT 1 FROM evidence WHERE doc_id=? AND title=?",
                (doc_id, title)).fetchone():
            summary["duplicates"] += 1
            continue

        db.insert_evidence(
            conn, doc_id=doc_id, claim={
                "title": title,
                "domain": domain,
                "severity": "high",
                "rationale": (
                    f"Official EU Safety Gate alert for {make} {model_key}: "
                    f"{desc_text or title_text}"),
                "inspection_advice": (
                    "Check whether this specific car has had the recall "
                    "remedy performed (VIN check at an official dealer); "
                    "if not, it is a free repair and a negotiating point."),
                "quote": desc_text or title_text,
                "quote_grounded": True,
                "engine_or_variant_hint": None,
            }, span_start=None, span_end=None,
            extractor_version=FEEDS_EXTRACTOR_VERSION)
        summary["ingested"] += 1
    return summary



def run(conn, *, getter=_http_get_bytes, only: tuple[str, str] | None = None) -> dict:
    """Ingest Safety Gate alerts for every catalog model (or one)."""
    models = [only] if only else catalog_models()
    per_model = {}
    for make, model_key in models:
        s = ingest_alerts(conn, make, model_key, getter=getter)
        per_model[f"{make}_{model_key}"] = s
        log.info("Safety Gate %s %s: %s", make, model_key, json.dumps(s))
    return per_model
