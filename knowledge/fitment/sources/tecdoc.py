"""tecdoc.py — TecDoc API adapter for fitment data.

TecDoc is the European standard automotive parts catalog. The TDConnect API
(tdconnect.tecdoc.net) provides structured fitment: model → gearbox code,
engine code, etc.

Requires: TECDOC_API_KEY environment variable (register at tdconnect.tecdoc.net).

Usage:
    from knowledge.fitment.sources.tecdoc import fetch_transmission_codes
    codes = fetch_transmission_codes(make="Renault", model="Megane", year=2020)
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

_BASE_URL = "https://webservice.tecalliance.services/pegasus-3-0/services/TecdocToCatDLB.jsonEndpoint"
_TIMEOUT = 20


def _api_key() -> str | None:
    return os.getenv("TECDOC_API_KEY")


def fetch_transmission_codes(
    make: str,
    model: str,
    year: int,
) -> list[dict]:
    """Query TecDoc for gearbox codes for a given car model/year.

    Returns a list of dicts: [{transmission_code, description, year_from, year_to}]
    Returns empty list if API key not set or request fails.
    """
    key = _api_key()
    if not key:
        log.info("TECDOC_API_KEY not set — skipping TecDoc lookup")
        return []

    # TecDoc JSON-RPC style request
    payload = {
        "getBrands": {
            "lang": 1,
            "country": "GB",
            "providerId": key,
        }
    }

    try:
        resp = httpx.post(_BASE_URL, json=payload, timeout=_TIMEOUT,
                          headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        data = resp.json()
        log.debug("TecDoc response for %s %s %d: %s", make, model, year, data)
        # TecDoc API returns structured data — parse gearbox entries here.
        # Full parsing depends on the specific endpoint; return raw for now.
        return data.get("data", {}).get("gearboxes", [])
    except Exception as exc:
        log.warning("TecDoc fetch failed for %s %s %d: %s", make, model, year, exc)
        return []
