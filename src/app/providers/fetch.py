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

#: The answers a site gives when it has decided it will not be read by this
#: fetcher. Cloudflare's bot rules answer 403 (sometimes 429, sometimes 503
#: with a challenge page), and a refusal is not a network failure: the page
#: exists, only this door is shut. Those are the ones worth one more rung.
REFUSED = (403, 429, 503)

_DROP = re.compile(
    r"<(script|style|noscript|nav|header|footer|aside|form|svg|template|iframe"
    r"|select|button|dialog|menu|object|canvas|picture|video|audio)(?![\w-])[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
#: Markup that is never prose, and that `_TAG` alone would leave behind as
#: text: comments (often whole commented-out blocks of markup), CDATA, the
#: `<head>` (its `<title>` is kept separately), and a `<script>` or `<style>`
#: the `MAX_BYTES` cut left without its closing tag.
_COMMENT = re.compile(r"<!--.*?(-->|\Z)|<!\[CDATA\[.*?(\]\]>|\Z)", re.DOTALL)
# `(?![\w-])` rather than `\b`: `\b` matches before a hyphen, so a custom
# element (`<button-group>`, `<video-js>`) would be read as the tag it starts
# with and scan the page for a closer it never has.
_HEAD = re.compile(r"<head(?![\w-])[^>]*>.*?</head>", re.IGNORECASE | re.DOTALL)
_TITLE = re.compile(r"<title(?![\w-])[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_UNCLOSED = re.compile(r"<(script|style)(?![\w-]).*\Z", re.IGNORECASE | re.DOTALL)
_MAIN = re.compile(r"<main(?![\w-])[^>]*>(.*)</main>", re.IGNORECASE | re.DOTALL)
_ANCHOR = re.compile(r"<a(?![\w-])[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
#: Around a link's text until `prose_lines` has read it: a menu is a run of
#: links, and once the tags are gone this is the only trace of which lines
#: were links. Control characters no page text carries.
LINK_OPEN, LINK_CLOSE = "\x01", "\x02"
#: A `<main>` with less text than this is a shell around a page drawn by
#: script, and the body is the better bet.
_MAIN_MIN_CHARS = 500
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
            if kind and not (
                kind.startswith("text/") or "html" in kind or "xml" in kind
            ):
                return ""
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read(MAX_BYTES).decode(charset, "replace")
    except urllib.error.HTTPError as error:
        if error.code in REFUSED:
            # The site answered, and its answer was a refusal aimed at this
            # app's own fetcher — the class B155 recorded. The hosted readers
            # are the next rung: they read the page from elsewhere, and the
            # browser after them reads it with a genuine fingerprint. "" from
            # a rung leaves the page unread exactly as before, never
            # half-read.
            from app.providers import browser, pagereader  # noqa: PLC0415 — optional rungs

            page = pagereader.read(url)
            if not page:
                page = browser.read(url)
            if page:
                log.info("a source refused the plain fetch and a later rung read it")
                return page
        log.info("could not read a source: HTTP %s", error.code)
        return ""
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        LookupError,
        ValueError,
    ) as error:
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

    body = _COMMENT.sub(" ", markup)
    title = _TITLE.search(body)
    body = _HEAD.sub(" ", body)
    body = _UNCLOSED.sub(" ", _DROP.sub(" ", body))
    main = _MAIN.search(body)
    if main and len(_TAG.sub("", main.group(1)).strip()) >= _MAIN_MIN_CHARS:
        body = main.group(1)
    if title:
        body = f"<p>{title.group(1)}</p>{body}"
    body = _ANCHOR.sub(lambda m: LINK_OPEN + m.group(1) + LINK_CLOSE, body)
    body = re.sub(r"</(p|div|li|h[1-6]|tr|br)\s*>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    body = _TAG.sub(" ", body)
    # Unescaped *after* the tags are gone: a page containing `&lt;script&gt;`
    # as text would otherwise become a tag on this line and be stripped.
    body = html.unescape(body)
    body = _SPACE.sub(" ", body)
    body = "\n".join(prose_lines(line.strip() for line in body.splitlines()))
    return _BLANK.sub("\n\n", body).strip()


#: A menu is a run of crumbs: short lines that are each one link and nothing
#: else (`Home`, `Log in`, `Acura`, `2019`). This many in a row, blank lines
#: aside, is navigation, not content. A line that is not a link (a table
#: cell, a list of fault names) is never a crumb, and neither is one that
#: mixes a figure with words (`6 GB RAM`).
MENU_RUN = 8
_CRUMB_WORDS = 3
_CRUMB_CHARS = 30
#: Characters that are code and almost never prose. A long line where they
#: are this dense is an inlined blob of script or data, not a sentence.
_CODE = set("{}[]<>=;$\\^~`")
_CODE_DENSITY = 0.08
_CODE_MIN_CHARS = 30


def _crumb(line: str) -> bool:
    if not (line.startswith(LINK_OPEN) and line.endswith(LINK_CLOSE)):
        return False
    line = line[1:-1].strip()
    if not (0 < len(line) <= _CRUMB_CHARS and len(line.split()) <= _CRUMB_WORDS
            and line[-1] not in ".!?:"):
        return False
    has_digit = any(char.isdigit() for char in line)
    has_letter = any(char.isalpha() for char in line)
    return not (has_digit and has_letter)


def _code(line: str) -> bool:
    if len(line) < _CODE_MIN_CHARS:
        return False
    return sum(char in _CODE for char in line) / len(line) >= _CODE_DENSITY


def prose_lines(lines) -> list[str]:
    """The lines worth a model's tokens: menus and inlined code removed.

    Every token a model reads costs time on a CPU and money on a meter, and
    a site's navigation is most of a listing page's first screen. What goes
    is decided by the shape of a line, never by its words, so it holds for
    any site in any language: a run of `MENU_RUN` links that are each a
    line of their own, and a line dense with code characters. The link
    marks (`LINK_OPEN`, `LINK_CLOSE`) are removed from what is kept.
    Grounding is unaffected: what a model is shown is what its quotes are
    checked against.
    """
    kept: list[str] = []
    run: list[int] = []
    for line in lines:
        if not line:
            kept.append(line)
            continue
        if _code(line):
            continue
        if _crumb(line):
            run.append(len(kept))
            kept.append(line)
            continue
        if len(run) >= MENU_RUN:
            for index in run:
                kept[index] = ""
        run = []
        kept.append(line)
    if len(run) >= MENU_RUN:
        for index in run:
            kept[index] = ""
    return [line.replace(LINK_OPEN, "").replace(LINK_CLOSE, "").strip()
            for line in kept]
