"""Reading a page, without a dependency and without pretending.

`ApiResearcher.extract` enforces grounding by checking that the model's quote
appears verbatim in `document.text`. That check is only as good as this
function: text that arrives mangled — entities left encoded, a nav menu
interleaved with the prose — makes an honest quote unfindable and the finding
is refused. So the extraction here is conservative rather than clever. It drops
what is certainly not prose (script, style, nav, header, footer, aside), strips
tags, unescapes entities, and collapses whitespace.

**Not trafilatura**, which does this far better, because it is in the
`pipeline` extra and the desktop binary does not carry it. If it *is* installed
it is used — a source checkout that has run the pipeline gets the better
extraction for free, and the frozen app degrades to the stdlib path rather than
failing to import.

A page it cannot read returns `""`, which `gather` already treats as "skip this
document". An empty string is a legitimate answer here, not an error.
"""

import html
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

from kriko.research import Fetched

log = logging.getLogger(__name__)

#: A research document is read for its prose. Anything past this is almost
#: certainly comments or boilerplate, and `extract` truncates to 12 000
#: characters anyway — fetching megabytes to discard them wastes the reader's
#: bandwidth and the run's wall-clock.
MAX_BYTES = 2_000_000
TIMEOUT = 30.0

#: Identifying the client is politeness, not disguise. A blank user agent is
#: refused by enough sites that it reads as a bug; a browser's is a lie.
USER_AGENT = "Kriko/1.0 (+https://github.com/Berbadov/kriko)"

_DROP = re.compile(
    r"<(script|style|noscript|nav|header|footer|aside|form|svg)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n{3,}")


#: Before the public web had the metadata this reads, so a date below it
#: is a misparse rather than an antique page.
_EARLIEST = date(1995, 1, 1)


def reader(timeout: float = TIMEOUT):
    """`fetch(url) -> Fetched(text, published_at)`, empty when unreadable.

    The engine accepts bare text from any reader and this one has the markup
    in hand, which is the only place a publication date exists: by the time
    prose comes out of `to_text` the date is gone with the rest of the
    metadata. Read here or not at all.
    """

    def fetch(url: str) -> Fetched:
        raw = _download(url, timeout)
        if not raw:
            return Fetched("")
        return Fetched(to_text(raw), published_at(raw))

    return fetch


def published_at(markup: str) -> str:
    """When the page says it was published, or "" when it does not say.

    Never the fetch time, and never a guess: a reader weighing how old a
    warning is needs the date the world put it out, and being handed today's
    date instead would make every source look current. A date outside
    `_EARLIEST`..today is a parser that has misread something rather than a
    genuinely antique page, so it is refused like any other absence.
    """
    try:
        import trafilatura  # noqa: PLC0415 — optional, see the module docstring
    except ImportError:
        return ""
    try:
        found = trafilatura.extract_metadata(markup)
    except Exception:  # noqa: BLE001 — a date is never worth a failed fetch
        return ""
    return _bounded(getattr(found, "date", "") or "")


def _bounded(value: str) -> str:
    stamp = str(value).strip()[:10]
    try:
        when = date.fromisoformat(stamp)
    except ValueError:
        return ""
    if when < _EARLIEST or when > datetime.now(timezone.utc).date():
        return ""
    return stamp


def _download(url: str, timeout: float) -> str:
    # http(s) only. `fetch` is handed URLs a search provider returned, and a
    # `file:` URL among them would read this machine's disk — urllib is happy
    # to do that, which makes the scheme check a boundary rather than a nicety.
    if not url.lower().startswith(("http://", "https://")):
        return ""
    request = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            kind = (response.headers.get_content_type() or "").lower()
            if kind and not (kind.startswith("text/") or "html" in kind or "xml" in kind):
                return ""
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read(MAX_BYTES).decode(charset, "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            LookupError, ValueError) as error:
        log.info("could not read a source: %s", type(error).__name__)
        return ""


def to_text(markup: str) -> str:
    """Markup in, prose out. Pure, so it is testable without a socket."""
    try:
        import trafilatura  # noqa: PLC0415 — optional, see the module docstring
    except ImportError:
        pass
    else:
        extracted = trafilatura.extract(markup) or ""
        if extracted.strip():
            return extracted.strip()

    body = _DROP.sub(" ", markup)
    body = re.sub(r"</(p|div|li|h[1-6]|tr|br)\s*>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = _TAG.sub(" ", body)
    # Unescaped *after* the tags are gone: a page containing `&lt;script&gt;`
    # as text would otherwise become a tag on this line and be stripped.
    body = html.unescape(body)
    body = _SPACE.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    return _BLANK.sub("\n\n", body).strip()
