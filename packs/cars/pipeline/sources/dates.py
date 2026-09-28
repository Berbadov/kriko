"""World-publish date extraction and sanity bounds — cars' own vocabulary of
*how* to read a publish date off a page or a video, never the engine's.

Two different facts get collapsed if this module is skipped: the day a
source was *fetched* (``documents.fetched_at``, stamped on every row by the
ledger itself) and the day it was *first put on the web* (``published_at``,
knowable only from what the page or video itself declares). A guess is worse
than a blank — every function here returns ``""`` the moment it cannot read
a real date off the source, and none of them ever substitutes fetch time,
today's date, or a URL-slug guess for a missing one.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

# The floor: content old enough to predate the public web (and, for the
# YouTube path, old enough to predate YouTube itself, 2005) cannot be a real
# publish date for a source this pipeline would ever discover — a parser that
# reports 1970 or 1899 has misread something, not found an antique. The
# ceiling: a page cannot be published in the future relative to the moment
# this process is fetching it. A page dates itself in *its* time zone, so the
# ceiling is the latest calendar date anywhere right now (UTC+14). Plain UTC
# dropped every page published "today" in Istanbul between 00:00 and 03:00.
_MIN_DATE = date(1995, 1, 1)
_LATEST_OFFSET = timedelta(hours=14)


def _today() -> date:
    return (datetime.now(timezone.utc) + _LATEST_OFFSET).date()


def _bounded(d: date, *, source: str) -> str:
    if d < _MIN_DATE or d > _today():
        log.warning(
            "published_at out of range for %s: %s (dropped, not stored)",
            source or "<unknown>", d.isoformat(),
        )
        return ""
    return d.isoformat()


def from_trafilatura_date(raw: str | None, *, source: str = "") -> str:
    """Normalize trafilatura/htmldate's ``date`` metadata field.

    That field is already ``YYYY-MM-DD`` or ``None`` — htmldate applies its
    own bounds too, but this is the pipeline's own decision, made explicit
    and tested rather than inherited silently from a dependency's defaults.
    """
    if not raw:
        return ""
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        log.warning(
            "unparseable published_at %r for %s (dropped, not stored)",
            raw, source or "<unknown>",
        )
        return ""
    return _bounded(d, source=source)


def from_yt_dlp_upload_date(raw: str | None, *, source: str = "") -> str:
    """Normalize yt-dlp's ``upload_date`` info-dict field (``YYYYMMDD``)."""
    if not raw:
        return ""
    try:
        d = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        log.warning(
            "unparseable upload_date %r for %s (dropped, not stored)",
            raw, source or "<unknown>",
        )
        return ""
    return _bounded(d, source=source)


def page_published_at(html: str, *, source: str = "") -> str:
    """Read a world-publish date off fetched HTML, or "" if there is none.

    Reads ``article:published_time``, JSON-LD ``datePublished`` and the rest
    of what htmldate looks at, via trafilatura's own metadata extraction —
    the same library already fetches and extracts the article text, so this
    is wiring an existing capability through, not a second date parser.
    """
    try:
        import trafilatura
    except ImportError:
        log.error("trafilatura not installed — run: pip install trafilatura")
        return ""
    try:
        meta = trafilatura.extract_metadata(html)
    except Exception as exc:
        log.debug("metadata extraction failed for %s: %s", source, exc)
        return ""
    return from_trafilatura_date(meta.date if meta else None, source=source)


def youtube_published_at(info: dict | None, *, source: str = "") -> str:
    """Read a video's upload date out of a yt-dlp ``extract_info`` result."""
    return from_yt_dlp_upload_date((info or {}).get("upload_date"), source=source)
