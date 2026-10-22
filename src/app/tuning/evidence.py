"""The evidence an answer is graded against: its pages, fetched again.

The grader does not take the answerer's word for what a page says. Every page
the answer links to, and every page the answerer says it read, is fetched here
with the app's own reader (public hosts only, redirects checked), and what
comes back is what the grader is shown. That fetch is also the test of
*links that open*: an address the answer gives that does not open is a link a
reader will meet as broken, and an address that was never read and does not
open is an invented one.

The fetch is injectable so a test (and a run with no network) supplies pages.
"""

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

#: Pages kept as evidence, and characters of each shown to the grader.
MAX_PAGES = 12
PAGE_CHARS = 6000
EXCERPT_CHARS = 1500

_URL = re.compile(r"https?://[^\s<>\"\]]+")
_TRAILING = ".,;:!?'*_"


def urls_in(text: str) -> list[str]:
    """The http(s) addresses in a piece of text, in order, once each."""
    found: list[str] = []
    for match in _URL.findall(str(text or "")):
        url = match.rstrip(_TRAILING)
        # A markdown link's closing parenthesis is not part of the address,
        # an address's own balanced one (a wiki title) is.
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        if urlsplit(url).netloc and url not in found:
            found.append(url)
    return found


def collect(answer_urls: list[str], read_urls: list[str],
            fetch: Callable[[str], object], *, question: str = "") -> list[dict]:
    """Fetch each page once. Every row says whether it opened and whether the
    answer links to it, whether the answerer read it, and carries the text.

    `fetch(url)` returns the page text or an object with `.text`; an empty
    text is a page that did not open.
    """
    from kriko.research.window import focus

    order = list(dict.fromkeys([*answer_urls, *read_urls]))[:MAX_PAGES]

    def one(url: str) -> dict:
        try:
            got = fetch(url)
            text = str(getattr(got, "text", got) or "").strip()
        except Exception:  # noqa: BLE001 - a page that will not open is a finding
            text = ""
        shown = focus(text, PAGE_CHARS, question.split()[:12]) if text else ""
        return {"url": url, "opens": bool(text), "chars": len(text), "text": shown,
                "in_answer": url in answer_urls, "read_by_answerer": url in read_urls}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, order))


def links_summary(pages: list[dict]) -> dict:
    """Which of the answer's own links open, which are broken, which were never read."""
    linked = [page for page in pages if page["in_answer"]]
    return {"total": len(linked),
            "open": sum(page["opens"] for page in linked),
            "broken": [page["url"] for page in linked if not page["opens"]],
            "unread": [page["url"] for page in linked if not page["read_by_answerer"]],
            "invented": [page["url"] for page in linked
                         if not page["opens"] and not page["read_by_answerer"]]}


def excerpt(page: dict) -> dict:
    """A page as the ledger keeps it: the address, whether it opened, a short excerpt."""
    return {"url": page["url"], "opens": page["opens"], "chars": page["chars"],
            "in_answer": page["in_answer"], "read_by_answerer": page["read_by_answerer"],
            "excerpt": page["text"][:EXCERPT_CHARS]}
