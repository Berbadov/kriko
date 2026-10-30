"""Presentation of product risk, dated evidence and quoted repair costs.

No failure probabilities are inferred from severity. Prices are historical
source quotes, never an expected ownership bill or a current seller offer.
"""

from datetime import UTC, datetime
from html import escape
import re
from urllib.parse import urlsplit

MONEY = re.compile(
    r"(?:[$€£]\s*\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|TRY|CAD|AUD))",
    re.IGNORECASE,
)
REPAIR = re.compile(r"\b(?:part|repair|replac\w*|labou?r|service|kit|assembly)\b", re.I)


def timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def freshness(store, claims: list[dict], *, days: int = 30) -> dict:
    """Oldest dated source behind the displayed evidence; unknown is not fresh.

    A saved check's creation or re-answer time is never a source verification.
    """
    dates = []
    unknown = 0
    seen = set()
    for claim in claims:
        for source in claim.get("sources") or []:
            key = (claim.get("pack_id", ""), source.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            row = store.execute(
                "SELECT retrieved_at FROM sources WHERE pack_id = ? AND url = ?", key,
            ).fetchone()
            date = timestamp(row["retrieved_at"]) if row else None
            if date and date <= datetime.now(UTC):
                dates.append(date)
            else:
                unknown += 1
    oldest = min(dates) if dates else None
    age = max(0, (datetime.now(UTC) - oldest).days) if oldest else None
    return {"last_verified": oldest.isoformat() if oldest else None,
            "age_days": age, "stale_after_days": days,
            "stale": age is None or age >= days or unknown > 0,
            "undated_sources": unknown,
            "basis": "Oldest source retrieval behind these findings; not a new quote verification."}


def costs(claims: list[dict]) -> dict:
    items = []
    missing = []
    for claim in claims:
        found = False
        for source in claim.get("sources") or []:
            if source.get("stance") == "refutes":
                continue
            quote = str(source.get("quote") or "")
            # Keep the money tied to a repair sentence, rather than picking up
            # the purchase price elsewhere in a long quote.
            for sentence in re.split(r"(?<=[.!?])\s+|\n", quote):
                prices = MONEY.findall(sentence)
                if not prices or not REPAIR.search(sentence) or not safe_url(source.get("url", "")):
                    continue
                found = True
                item = {"claim_id": claim.get("claim_id", ""), "title": claim.get("title", ""),
                        "prices": prices, "quote": sentence, "url": source["url"]}
                if item not in items:
                    items.append(item)
        if not found:
            missing.append(claim.get("title", "Unknown part"))
    return {"items": items, "missing": missing,
            "note": "Quoted repair/part costs, in each source's currency. Compatibility, labour, tax and current availability need checking. Failure probability is unknown, so no expected-cost total is calculated."}


def safe_url(value: str) -> str:
    try:
        parts = urlsplit(str(value))
        return str(value) if parts.scheme in ("http", "https") and parts.hostname else ""
    except ValueError:
        return ""


def report(row: dict, fresh: dict, forecast: dict) -> str:
    """A self-contained, script-free report suitable for sharing or printing."""
    esc = lambda value: escape(str(value or ""), quote=True)  # noqa: E731
    response = row.get("response") or {}
    sections = []
    for claim in response.get("claims") or []:
        sources = []
        for source in claim.get("sources") or []:
            url = safe_url(source.get("url", ""))
            sources.append(f'<li><a href="{esc(url)}">{esc(url)}</a>'
                           f'<p>{esc(source.get("stance"))}</p>'
                           f'<blockquote>{esc(source.get("quote"))}</blockquote></li>')
        sections.append(f'<section><h2>{esc(claim.get("title"))}</h2>'
                        f'<p>Severity: {esc(claim.get("severity"))}</p>'
                        f'<p>{esc(claim.get("body"))}</p><p>{esc(claim.get("advice"))}</p>'
                        f'<ul>{"".join(sources)}</ul></section>')
    cost_lines = "".join(f'<li>{esc(one["title"])}: {esc(", ".join(one["prices"]))}'
                         f'<blockquote>{esc(one["quote"])}</blockquote></li>' for one in forecast["items"])
    url = safe_url((row.get("request") or {}).get("url", ""))
    return (f'<!doctype html><html lang="en"><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width"><title>{esc(row.get("label"))} — Kriko</title>'
            '<style>body{max-width:850px;margin:40px auto;padding:0 24px;font:16px/1.6 system-ui;color:#17221c}'
            'h1,h2{line-height:1.2}section{border-top:1px solid #ccd5ce;margin-top:24px}blockquote{white-space:pre-wrap;'
            'border-left:3px solid #8a9e90;padding-left:16px}a{overflow-wrap:anywhere}@media print{body{margin:0}}</style>'
            f'<body><p>Kriko · Saved product report</p><h1>{esc(row.get("label"))}</h1>'
            f'<p>Saved: {esc(row.get("created_at"))}</p><p>Last verified (source retrieval): '
            f'{esc(fresh["last_verified"] or "Unknown")} · {"Stale or incomplete dates" if fresh["stale"] else "Within freshness threshold"}</p>'
            f'<p>{esc(fresh["basis"])}</p><p>Listing: <a href="{esc(url)}">{esc(url)}</a></p>'
            f'<p>Coverage: {esc(response.get("coverage"))}. Missing findings do not establish that a product is safe.</p>'
            f'{"".join(sections) or "<p>No sourced findings recorded.</p>"}'
            f'<h2>Cost forecast</h2><p>{esc(forecast["note"])}</p><ul>{cost_lines}</ul>'
            f'<p>No price recorded for: {esc("; ".join(forecast["missing"]) or "None")}</p>'
            '<p>Print this report and choose Save as PDF to keep a PDF copy.</p></body></html>')
