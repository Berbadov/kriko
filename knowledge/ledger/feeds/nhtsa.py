"""NHTSA (US) recalls feed → structured documents + pre-structured evidence.

API: free, keyless JSON — https://api.nhtsa.gov/recalls/recallsByVehicle

Attribution design (per resolve.py semantics):
- body/electrical-class recalls get target_hint = the model's *_body/*_elec
  part (catalog-derived), so resolution lands them in the same model-level
  part files the legacy catalog keeps such recalls in.
- powertrain recalls get target_hint="" — they resolve ONLY when the recall
  text names a discriminative catalog code (alias path, e.g. "DSG"→dq200);
  otherwise they stay unresolved (retained in the ledger, never clustered,
  zero cost). Better a recall sit unresolved than be filed against the wrong
  engine.

Known gap: NHTSA is US-market — Renault (Megane/Clio) sells nothing there, so
this feed covers VW only. EU Safety Gate/RAPEX + TR SGM ingesters are the
Renault answer; the public Safety Gate API shape needs more reverse-engineering
(tracked in backlog B17). The ingester pattern is the deliverable here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from knowledge.ledger import db

log = logging.getLogger(__name__)

API = "https://api.nhtsa.gov/recalls/recallsByVehicle"
VARIANTS_DIR = Path(__file__).parent.parent.parent.parent / "backend" / "data" / "variants"

# Distinct from backfill (0) and langextract (2): marks pre-structured rows.
FEEDS_EXTRACTOR_VERSION = 100

# NHTSA Component prefix → (claim domain, routing class). Routing class:
# "elec" → model's *_elec part hint, "body" → *_body hint, "alias" → no hint.
_COMPONENT_MAP = {
    "ELECTRICAL SYSTEM": ("electrical", "elec"),
    "INSTRUMENT CLUSTER": ("electrical", "elec"),
    "BACK OVER PREVENTION": ("electrical", "elec"),
    "ENGINE AND ENGINE COOLING": ("engine", "alias"),
    "ENGINE": ("engine", "alias"),
    "POWER TRAIN": ("transmission", "alias"),
    "FUEL SYSTEM": ("fuel system", "alias"),
    "FUEL/PROPULSION SYSTEM": ("fuel system", "alias"),
    "HYBRID PROPULSION SYSTEM": ("fuel system", "alias"),
    "SERVICE BRAKES": ("brakes", "body"),
    "PARKING BRAKE": ("brakes", "body"),
    "SUSPENSION": ("suspension", "body"),
    "STEERING": ("suspension", "body"),
    "AIR BAGS": ("body", "body"),
    "SEAT BELTS": ("body", "body"),
    "STRUCTURE": ("body", "body"),
    "LATCHES/LOCKS/LINKAGES": ("body", "body"),
    "VISIBILITY": ("body", "body"),
    "EXTERIOR LIGHTING": ("electrical", "body"),
    "TIRES": ("suspension", "body"),
    "WHEELS": ("suspension", "body"),
    "SEATS": ("body", "body"),
    "EQUIPMENT": ("general", "body"),
    "FORWARD COLLISION AVOIDANCE": ("electrical", "elec"),
    "LANE DEPARTURE": ("electrical", "elec"),
}


def _classify(component: str) -> tuple[str, str]:
    """NHTSA component string → (claim domain, routing class)."""
    comp = (component or "").upper()
    for prefix, (domain, route) in sorted(
            _COMPONENT_MAP.items(), key=lambda kv: -len(kv[0])):
        if comp.startswith(prefix):
            return domain, route
    return "general", "body"


def _http_get(url: str) -> dict:
    import httpx
    resp = httpx.get(url, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_recalls(make: str, model: str, year: int, *, getter=_http_get) -> list[dict]:
    """One year of recalls for make/model. US-model naming; absent → []."""
    data = getter(f"{API}?make={make}&model={model}&modelYear={year}")
    return data.get("results") or []


def catalog_model_years(make: str, model: str) -> list[int]:
    """Production year span for a catalog model, read off the variants YAML."""
    path = VARIANTS_DIR / f"{make}_{model}.yaml"
    if not path.exists():
        return []
    rows = yaml.safe_load(path.read_text()) or []
    lo = min((r["year_from"] for r in rows if r.get("year_from")), default=None)
    hi = max((r.get("year_to") or 2026 for r in rows), default=None)
    if lo is None or hi is None:
        return []
    return list(range(lo, hi + 1))


def _model_part_hint(make: str, model: str, route: str) -> str:
    """The model's *_body/*_elec part id, derived from catalog part files."""
    if route == "alias":
        return ""
    prefix = model.replace("_", "")
    parts_dir = VARIANTS_DIR.parent / "parts"
    for p in parts_dir.glob(f"*/{prefix}_{route}.yaml"):
        return p.stem
    return ""


def _doc_text(rec: dict) -> str:
    return (
        f"NHTSA recall {rec.get('NHTSACampaignNumber', '')} — "
        f"{rec.get('Component', '')}\n"
        f"Summary: {rec.get('Summary', '')}\n"
        f"Consequence: {rec.get('Consequence', '')}\n"
        f"Remedy: {rec.get('Remedy', '')}"
    )


def ingest_recalls(conn, make: str, model_key: str, *, us_model: str | None = None,
                   getter=_http_get) -> dict:
    """Fetch + ingest all recalls for one catalog model. Idempotent via
    campaign-number dedup and the documents text-hash. Returns a summary."""
    us_model = us_model or model_key
    years = catalog_model_years(make, model_key)
    summary = {"years": len(years), "campaigns": 0, "ingested": 0,
               "duplicates": 0, "errors": 0}
    seen_campaigns: set[str] = set()
    for year in years:
        try:
            recalls = fetch_recalls(make, us_model, year, getter=getter)
        except Exception as exc:
            log.warning("NHTSA fetch failed for %s %s %s: %s",
                        make, model_key, year, exc)
            summary["errors"] += 1
            continue
        for rec in recalls:
            campaign = rec.get("NHTSACampaignNumber")
            if not campaign or campaign in seen_campaigns:
                summary["duplicates"] += 1
                continue
            seen_campaigns.add(campaign)
            summary["campaigns"] += 1

            component = rec.get("Component", "")
            domain, route = _classify(component)
            hint = _model_part_hint(make, model_key, route)
            text = _doc_text(rec)
            doc_id = db.insert_document(
                conn, url=f"nhtsa:recall:{campaign}", source_type="structured",
                raw_text=text, site_or_channel="NHTSA", target_hint=hint)
            summary_part = rec.get("Summary", "")
            title = f"Recall {campaign}: {component.lower()}"
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
                        f"Official NHTSA safety recall for {make} {model_key} "
                        f"({rec.get('ModelYear', '?')}): {summary_part} "
                        f"Consequence: {rec.get('Consequence', '')}"),
                    "inspection_advice": (
                        "Check whether this specific car has had the recall "
                        "remedy performed (VIN check at an official dealer); "
                        "if not, it is a free repair and a negotiating point."),
                    "quote": summary_part,
                    "quote_grounded": True,
                    "engine_or_variant_hint": None,
                }, span_start=None, span_end=None,
                extractor_version=FEEDS_EXTRACTOR_VERSION)
            summary["ingested"] += 1
    return summary


def catalog_models() -> list[tuple[str, str]]:
    """(make, model) pairs straight off the variants dir — coverage grows with
    the catalog, no hand-enumerated list to go stale."""
    out = []
    for p in sorted(VARIANTS_DIR.glob("*.yaml")):
        make_model = p.stem.split("_", 1)
        if len(make_model) == 2:
            out.append((make_model[0], make_model[1]))
    return out


def run(conn, *, getter=_http_get, only: tuple[str, str] | None = None) -> dict:
    """Ingest NHTSA recalls for every catalog model (or one).

    Catalog model keys (golf_7) drive file lookups; the NHTSA query uses the
    base US model name (golf) — generation suffixes are a catalog concept."""
    models = [only] if only else catalog_models()
    per_model = {}
    for make, model_key in models:
        us_model = model_key.split("_")[0]
        s = ingest_recalls(conn, make, model_key, us_model=us_model, getter=getter)
        per_model[f"{make}_{model_key}"] = s
        log.info("NHTSA %s %s (as %s): %s", make, model_key, us_model,
                 json.dumps(s))
    return per_model

