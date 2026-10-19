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
import time
import urllib.error
import urllib.request
from app import htmlscan
from app.providers import egress, network
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

_DROP_NAMES = ("script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "template",
               "iframe", "select", "button", "dialog", "menu", "object", "canvas", "picture", "video", "audio")
#: Markup that is never prose, and that `_TAG` alone would leave behind as
#: text: comments (often whole commented-out blocks of markup), CDATA, the
#: `<head>` (its `<title>` is kept separately), and a `<script>` or `<style>`
#: the `MAX_BYTES` cut left without its closing tag.
_COMMENT = re.compile(r"<!--.*?(-->|\Z)|<!\[CDATA\[.*?(\]\]>|\Z)", re.DOTALL)
# `(?![\w-])` rather than `\b`: `\b` matches before a hyphen, so a custom
# element (`<button-group>`, `<video-js>`) would be read as the tag it starts
# with and scan the page for a closer it never has.
_UNCLOSED = re.compile(r"<(script|style)(?![\w-]).*\Z", re.IGNORECASE | re.DOTALL)
#: Around a link's text until `prose_lines` has read it: a menu is a run of
#: links, and once the tags are gone this is the only trace of which lines
#: were links. Control characters no page text carries.
LINK_OPEN, LINK_CLOSE = "\x01", "\x02"
#: A `<main>` with less text than this is a shell around a page drawn by
#: script, and the body is the better bet.
_MAIN_MIN_CHARS = 500
# `[^<>]`, not `[^>]`: with every `<` allowed inside, a page of `<nav` and no `>` made each
# one scan to the end of the page. A `<` inside a tag starts the next tag.
_TAG = re.compile(r"<[^<>]+>")
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

    timeout_default = timeout

    def fetch(url: str, *, timeout: float | None = None, check_cancelled=None,
              allow_fallback: bool = True, allow_private: bool = False) -> Fetched:
        request_timeout = (min(timeout, timeout_default)
                           if timeout is not None else timeout_default)
        if request_timeout <= 0:
            return Fetched("")
        began = time.monotonic()
        ladder_ends = began + 2 * request_timeout
        raw = _download(url, request_timeout, check_cancelled=check_cancelled,
                        allow_fallback=allow_fallback, ladder_ends=ladder_ends,
                        allow_private=allow_private)
        if not raw:
            return Fetched("")
        text = to_text(raw)
        if challenged(text):
            # Answered 200, with a bot check where the page should be. It is
            # the same refusal a 403 is, and was taken for a page (measured:
            # 145 and 89 characters of "Drag the handle to the target" and
            # "Checking your browser", counted as read). Climb from here,
            # inside what is left of the page's time.
            if not allow_fallback:
                return Fetched("")
            if check_cancelled is not None:
                check_cancelled()
            raw = _climb(url, ladder_ends, check_cancelled=check_cancelled,
                         allow_private=allow_private)
            if not raw:
                return Fetched("")
            text = to_text(raw)
            if challenged(text):
                return Fetched("")
        return Fetched(text, published_at(raw))

    fetch.supports_cancel_check = True  # type: ignore[attr-defined]
    fetch.supports_timeout = True  # type: ignore[attr-defined]
    fetch.supports_fallback = True  # type: ignore[attr-defined]

    return fetch


def markup(url: str, timeout: float = TIMEOUT, *, check_cancelled=None) -> str:
    """The page's raw markup by the plain fetch alone, "" when it will not come.

    No later rung: this is for a page Kriko re-reads in the background on the
    reader's behalf (a price watch), and a background job must never start a
    browser or ask a hosted reader to fetch a shop on their behalf.
    """
    return _download(url, timeout, check_cancelled=check_cancelled, allow_fallback=False)


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


#: The least a browser needs to open a page and print it; with less left in a
#: page's budget the rung is not tried, since it would only be killed.
BROWSER_MIN_SECONDS = 15.0


class FetchCancelled(Exception):
    """A caller stopped waiting for a page; do not try another reader rung."""


def _download(url: str, timeout: float, *, check_cancelled=None,
              allow_fallback: bool = True, ladder_ends: float | None = None,
              allow_private: bool = False) -> str:
    # http(s) only. `fetch` is handed URLs a search provider returned, and a
    # `file:` URL among them would read this machine's disk — urllib is happy
    # to do that, which makes the scheme check a boundary rather than a nicety.
    if not url.lower().startswith(("http://", "https://")):
        return ""
    # C2: this URL came from a search result or a source a model named. A host
    # that is this machine or the reader's own network is refused — the sidecar's
    # own unauthenticated API and the cloud metadata address are both one
    # search-result away. See `providers/egress.py` for the limits of the check.
    refusal = egress.reason_to_refuse(url, allow_private=allow_private)
    if refusal:
        log.warning("refused a page fetch: %s", refusal)
        return ""
    if check_cancelled is not None:
        check_cancelled()
    request = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
    # A page costs at most twice `timeout` in all, whichever rungs it climbs.
    # Each rung had its own 45 s on top of the plain fetch's, so one refused
    # page could hold a run for a minute and a half (measured: 48 s of an
    # 8 s reader, on a page that answered 429).
    if ladder_ends is None:
        ladder_ends = time.monotonic() + 2 * timeout
    plain_ends = time.monotonic() + timeout
    try:
        options = {"check": check_cancelled} if check_cancelled is not None else {}
        with network.urlopen(request, timeout=timeout, guard_redirects=not allow_private,
                             **options) as response:
            kind = (response.headers.get_content_type() or "").lower()
            if kind and not (
                kind.startswith("text/") or "html" in kind or "xml" in kind
            ):
                return ""
            charset = response.headers.get_content_charset() or "utf-8"
            body_timeout = max(0.0, min(timeout, plain_ends - time.monotonic()))
            raw = _body(response, body_timeout, check_cancelled=check_cancelled)
        if check_cancelled is not None:
            check_cancelled()
        return raw.decode(charset, "replace")
    except urllib.error.HTTPError as error:
        if error.code in REFUSED and allow_fallback:
            if check_cancelled is not None:
                check_cancelled()
            page = _climb(url, ladder_ends, check_cancelled=check_cancelled,
                          allow_private=allow_private)
            if page:
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


def _body(response, timeout: float, *, check_cancelled=None) -> bytes:
    """What the page sent within `timeout` seconds in all, at most `MAX_BYTES`.

    `urlopen`'s timeout bounds each wait on the socket, not the page: a server
    that drips a byte every few seconds never trips it (measured: 48 s on an
    8 s timeout, and the run waited for it). The budget is for the whole
    body, and what had arrived when it ran out is kept, since prose cut short
    is still prose the model can quote, exactly as the `MAX_BYTES` cut is.
    """
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    size = 0
    while size < MAX_BYTES and time.monotonic() < deadline:
        if check_cancelled is not None:
            check_cancelled()
        chunk = response.read(min(65536, MAX_BYTES - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def _climb(url: str, ladder_ends: float, *, check_cancelled=None,
           allow_private: bool = False) -> str:
    """The page through the later rungs, within what is left of its time.

    The site answered, and its answer was a refusal aimed at this app's own
    fetcher — the class B155 recorded. The hosted readers are the next rung:
    they read the page from elsewhere, and the browser after them reads it
    with a genuine fingerprint. "" from a rung leaves the page unread, never
    half-read.
    """
    from app.providers import browser, pagereader  # noqa: PLC0415 — optional rungs

    left = ladder_ends - time.monotonic()
    if left > 1.0:
        if check_cancelled is not None:
            page = pagereader.read(url, timeout=left, check_cancelled=check_cancelled,
                                   allow_private=allow_private)
        else:
            page = pagereader.read(url, timeout=left, allow_private=allow_private)
    else:
        page = ""
    left = ladder_ends - time.monotonic()
    if not page and left >= BROWSER_MIN_SECONDS:
        if check_cancelled is not None:
            page = browser.read(url, timeout=left, check_cancelled=check_cancelled,
                                allow_private=allow_private)
        else:
            page = browser.read(url, timeout=left, allow_private=allow_private)
    if page:
        log.info("a source refused the plain fetch and a later rung read it")
    return page


#: A bot check is a few lines; a page that says "blocked" in a long article
#: is an article. Above this many characters of prose it is read as a page.
CHALLENGE_MAX_CHARS = 600


def challenged(text: str) -> bool:
    """Whether what came back is a bot check rather than the page.

    By the shape of the answer: short, and in the words these pages are made
    of (`politeness.looks_blocked`, the one list of them). Never by a site's
    name, so it holds for every host a search returns.
    """
    from kriko.research.politeness import looks_blocked  # noqa: PLC0415

    stripped = " ".join(text.split())
    return 0 < len(stripped) <= CHALLENGE_MAX_CHARS and looks_blocked(200, stripped)


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
    titles = htmlscan.inner_texts(body, ("title",), limit=1)
    body = htmlscan.blocks(body, ("head",), lambda inner: " ")
    body = _UNCLOSED.sub(" ", htmlscan.blocks(body, _DROP_NAMES, lambda inner: " "))
    main = htmlscan.last_block(body, "main")
    if main is not None and len(_TAG.sub("", main).strip()) >= _MAIN_MIN_CHARS:
        body = main
    if titles:
        body = f"<p>{titles[0]}</p>{body}"
    body = htmlscan.blocks(body, ("a",), lambda inner: LINK_OPEN + inner + LINK_CLOSE)
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
