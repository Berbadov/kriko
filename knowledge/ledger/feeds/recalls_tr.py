"""TR SGM (Turkish Ministry recall system) feed -> structured documents + evidence.

API: public JSON -- https://www.sanayi.gov.tr/sgm/api/recalls
  ?make=<make>&model=<model>
  Response shape: {"recalls": [...], "total": int}
  Each recall: {"recallNumber": str, "component": str, "summary": str,
                "consequence": str, "remedy": str, "modelYear": str}

This covers the Turkish market -- Renault Megane/Clio are sold extensively in TR.
Complements NHTSA (US/VW-only) and EU Safety Gate (EU-wide).

STATUS (validated 2026-08-02): BLOCKED. sanayi.gov.tr now answers non-browser
clients with an anti-bot JS challenge (TSPD cookie), both on the API path and
on the site itself — a plain HTTP client no longer receives JSON. The ingester
is kept (idempotent, errors counted not fatal) so the feed can be re-enabled
when a working route exists (headless-browser fetch, an official alternative
source, or if the wall is lifted); see backlog B17.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from knowledge.ledger import db
from knowledge.ledger.feeds import (VARIANTS_DIR, catalog_models,
                                    model_part_hint as _model_part_hint)

log = logging.getLogger(__name__)

API = "https://www.sanayi.gov.tr/sgm/api/recalls"

FEEDS_EXTRACTOR_VERSION = 102

_COMPONENT_MAP = {
    "motor": ("engine", "alias"),
    "engine": ("engine", "alias"),
    "sanzman": ("transmission", "alias"),
    "transmission": ("transmission", "alias"),
    "gearbox": ("transmission", "alias"),
    "fren": ("brakes", "body"),
    "brake": ("brakes", "body"),
    "airbag": ("body", "body"),
    "elektrik": ("electrical", "elec"),
    "electrical": ("electrical", "elec"),
    "direksiyon": ("suspension", "body"),
    "steering": ("suspension", "body"),
    "yakıt": ("fuel system", "alias"),
    "fuel": ("fuel system", "alias"),
    "koltuk": ("body", "body"),
    "seat": ("body", "body"),
}


def _classify(text: str) -> tuple[str, str]:
    """TR SGM component/description -> (claim domain, routing class)."""
    text_lower = (text or "").lower()
    for keyword, (domain, route) in sorted(
            _COMPONENT_MAP.items(), key=lambda kv: -len(kv[0])):
        if keyword in text_lower:
            return domain, route
    return "general", "body"


def _http_get(url: str) -> dict:
    import httpx
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def fetch_recalls(make: str, model: str, *, getter=_http_get) -> list[dict]:
    """Search TR SGM for make+model recalls."""
    data = getter(f"{API}?make={make}&model={model}")
    return data.get("recalls", [])



def _doc_text(rec: dict) -> str:
    summary = rec.get("summary", "")
    consequence = rec.get("consequence", "")
    return f"{summary}. Consequence: {consequence}" if consequence else summary


def ingest_recalls(conn, make: str, model_key: str, *,
                   getter=_http_get) -> dict:
    """Ingest TR SGM recalls for one catalog model. Idempotent."""
    summary = {"recalls": 0, "ingested": 0, "duplicates": 0, "errors": 0}
    us_model = model_key.split("_")[0]
    try:
        recalls = fetch_recalls(make, us_model, getter=getter)
    except Exception as exc:
        log.warning("TR SGM fetch failed for %s %s: %s", make, model_key, exc)
        summary["errors"] += 1
        return summary

    seen_numbers: set[str] = set()
    for rec in recalls:
        summary["recalls"] += 1
        rec_number = rec.get("recallNumber", "")
        if not rec_number:
            continue
        if rec_number in seen_numbers:
            summary["duplicates"] += 1
            continue
        seen_numbers.add(rec_number)

        component = rec.get("component", "")
        summary_text = rec.get("summary", "")
        combined = f"{component} {summary_text}"
        domain, route = _classify(combined)
        hint = _model_part_hint(make, model_key, route)
        text = _doc_text(rec)

        doc_id = db.insert_document(
            conn, url=f"sgm:recall:{rec_number}", source_type="structured",
            raw_text=text, site_or_channel="TR SGM", target_hint=hint)

        title = f"TR Recall {rec_number}: {component.lower()}"
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
                    f"Official TR SGM recall for {make} {model_key} "
                    f"({rec.get('modelYear', '?')}): {summary_text} "
                    f"Consequence: {rec.get('consequence', '')}"),
                "inspection_advice": (
                    "Check whether this specific car has had the recall "
                    "remedy performed (VIN check at an official dealer); "
                    "if not, it is a free repair and a negotiating point."),
                "quote": summary_text,
                "quote_grounded": True,
                "engine_or_variant_hint": None,
            }, span_start=None, span_end=None,
            extractor_version=FEEDS_EXTRACTOR_VERSION)
        summary["ingested"] += 1
    return summary



def run(conn, *, getter=_http_get, only: tuple[str, str] | None = None) -> dict:
    """Ingest TR SGM recalls for every catalog model (or one)."""
    models = [only] if only else catalog_models()
    per_model = {}
    for make, model_key in models:
        s = ingest_recalls(conn, make, model_key, getter=getter)
        per_model[f"{make}_{model_key}"] = s
        log.info("TR SGM %s %s: %s", make, model_key, json.dumps(s))
    return per_model
