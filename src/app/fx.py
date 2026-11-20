"""Today's reference rates, from the Central Bank's public XML.

`GET /api/fx/tcmb` is a press, never a poll: the screen fetches only when the
reader asks for today's rates, and the reply says where the numbers came from
and which bulletin day they belong to. No key, no account, one host.

The rates are **TRY per one unit** of the foreign currency, which is TCMB's own
direction (`ForexSelling`). The estimate's screen uses that table for every
conversion it shows, so one direction is used everywhere.

Nothing here is stored in the engine's knowledge store or in `app.sqlite`: the
reader's typed rates stay on the estimate, and a fetched table is only handed
back to the screen that asked.
"""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

TCMB_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
#: The bulletin is a few dozen KB. A wrong URL or a captive portal cannot
#: stream into this process.
MAX_BYTES = 512 * 1024
TIMEOUT = 15
USER_AGENT = "kriko-fx"

_cache: dict[str, dict] = {}


def parse_tcmb(text: str) -> dict:
    """`{date, bulletin, rates, source}` from the bulletin's XML.

    A currency whose selling rate is blank (TCMB leaves some quotes empty) is
    simply absent: the screen then says it has no rate, rather than converting
    at zero.
    """
    root = ET.fromstring(text)
    bulletin_date = str(root.attrib.get("Tarih") or "")
    bulletin = str(root.attrib.get("Bulten_No") or "")
    rates: dict[str, float] = {"TRY": 1.0}
    for currency in root.findall("Currency"):
        code = str(currency.attrib.get("Kod") or currency.attrib.get("CurrencyCode") or "").upper()
        if not code:
            continue
        unit_text = _text(currency, "Unit") or "1"
        selling = _text(currency, "ForexSelling")
        try:
            unit = float(unit_text.replace(",", "."))
            value = float(selling.replace(",", "."))
        except ValueError:
            continue
        if unit <= 0 or value <= 0:
            continue
        rates[code] = round(value / unit, 6)
    return {
        "base": "TRY",
        "date": _iso(bulletin_date),
        "bulletin": bulletin,
        "rates": rates,
        "source": "TCMB",
        "url": TCMB_URL,
    }


def today_rates(*, force: bool = False) -> dict:
    """The cached bulletin for today, or a fresh read of the public XML."""
    key = date.today().isoformat()
    if not force and key in _cache:
        return _cache[key]
    request = urllib.request.Request(TCMB_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - fixed https host
        raw = response.read(MAX_BYTES)
    payload = parse_tcmb(raw.decode("utf-8"))
    payload["fetched_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _cache[key] = payload
    return payload


def _text(node: ET.Element, tag: str) -> str:
    found = node.find(tag)
    return "" if found is None or found.text is None else found.text.strip()


def _iso(bulletin_date: str) -> str:
    """`19.11.2026` (the bulletin's spelling) as `2026-11-19`, or as sent."""
    try:
        day, month, year = bulletin_date.split(".")
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return bulletin_date
