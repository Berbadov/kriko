"""Direct search with caching and provider cooldowns; no hosted MCP dependency.

OpenSERP remains the preferred local service. This is the keyless fallback:
read public result pages, then fetch the original sources through our reader.
Challenges and rate limits are failures, never source evidence.
"""

import base64
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from kriko.research.politeness import LocalSearchError

PROVIDERS = (
    ("duckduckgo", "https://html.duckduckgo.com/html/?q={query}"),
    ("bing", "https://www.bing.com/search?q={query}&setlang=en-US"),
    ("brave", "https://search.brave.com/search?q={query}&source=web"),
)
TIMEOUT = 12
CACHE_SECONDS = 900
COOLDOWN_SECONDS = 600
MAX_BYTES = 2_000_000
_DEFAULT_SEARCH = None
_DEFAULT_LOCK = threading.Lock()


def default_searcher():
    """Share caches and cooldowns between jobs in this process."""
    global _DEFAULT_SEARCH
    with _DEFAULT_LOCK:
        if _DEFAULT_SEARCH is None:
            _DEFAULT_SEARCH = searcher()
        return _DEFAULT_SEARCH


class Results(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hits = []
        self.heading = 0
        self.link = None
        self.title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h2":
            self.heading += 1
        classes = attrs.get("class", "").split()
        if tag == "a" and (set(classes) & {"result__a", "heading-serpresult", "snippet-title"} or self.heading):
            self.link = attrs.get("href", "")
            self.title = []

    def handle_data(self, data):
        if self.link is not None:
            self.title.append(data)

    def handle_endtag(self, tag):
        if tag == "h2":
            self.heading = max(0, self.heading - 1)
        if tag != "a" or self.link is None:
            return
        url = urllib.parse.urljoin("https://html.duckduckgo.com", self.link)
        parts = urllib.parse.urlsplit(url)
        if parts.hostname in ("duckduckgo.com", "html.duckduckgo.com"):
            url = urllib.parse.parse_qs(parts.query).get("uddg", [""])[0]
            parts = urllib.parse.urlsplit(url)
        if parts.hostname in ("bing.com", "www.bing.com") and parts.path == "/ck/a":
            target = urllib.parse.parse_qs(parts.query).get("u", [""])[0]
            if target.startswith("a1"):
                try:
                    encoded = target[2:]
                    url = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
                    parts = urllib.parse.urlsplit(url)
                except (ValueError, UnicodeError):
                    self.link = None
                    return
        if parts.scheme in ("http", "https") and parts.hostname and not parts.username:
            if parts.hostname not in ("bing.com", "www.bing.com", "duckduckgo.com", "html.duckduckgo.com", "search.brave.com"):
                if url not in {hit["url"] for hit in self.hits}:
                    self.hits.append({"url": url, "title": " ".join("".join(self.title).split()),
                                      "site": parts.hostname})
        self.link = None


def parse(body: str) -> list[dict]:
    if re.search(r'anomaly-modal|id=["\'][^"\']*captcha|verify you are human|unusual traffic', body, re.I):
        raise LocalSearchError("the search provider returned a challenge")
    parser = Results()
    parser.feed(body)
    return parser.hits


def relevant(hit: dict, query: str) -> bool:
    """Reject result sets that ignored the product's search terms."""
    words = lambda text: {word for word in re.findall(r"[\w]+", text.casefold()) if len(word) > 2}
    generic = {"the", "and", "for", "with", "problems", "failures", "failure",
               "faults", "owner", "owners", "reports", "repair", "repairs",
               "reliability", "common", "reviews", "documented"}
    wanted = words(query) - generic
    found = words(str(hit.get("title") or "") + " " + str(hit.get("url") or ""))
    return not wanted or len(wanted & found) >= min(2, len(wanted))


def searcher(*, opener=None, clock=time.monotonic, providers=PROVIDERS):
    """A search callable with an injectable network boundary for tests.

    Calls are serialized: a larger source budget does not burst an engine.
    After a refusal we skip that engine for ten minutes and use another.
    """
    open_url = opener or urllib.request.urlopen
    cache = {}
    cooldown = {}
    lock = threading.Lock()

    def search(query: str, limit: int = 5) -> list[dict]:
        count = max(1, min(50, int(limit)))
        key = (" ".join(query.split()).casefold(), count)
        failures = []
        with lock:
            now = clock()
            cached = cache.get(key)
            if cached and now - cached[0] < CACHE_SECONDS:
                return [dict(hit) for hit in cached[1]]
            for name, template in providers:
                if cooldown.get(name, 0) > now:
                    failures.append(f"{name} is cooling down")
                    continue
                url = template.format(query=urllib.parse.quote_plus(query))
                from app.version import app_version
                request = urllib.request.Request(url, headers={
                    "User-Agent": f"kriko/{app_version()} (+https://github.com/Berbadov/kriko)",
                    "Accept": "text/html",
                })
                try:
                    with open_url(request, timeout=TIMEOUT) as response:
                        hits = parse(response.read(MAX_BYTES).decode("utf-8", "replace"))
                        found = [hit for hit in hits if relevant(hit, query)][:count]
                except (urllib.error.URLError, OSError, LocalSearchError) as error:
                    cooldown[name] = clock() + COOLDOWN_SECONDS
                    failures.append(f"{name}: {error}")
                    continue
                if found:
                    if len(cache) >= 256:
                        cache.pop(next(iter(cache)))
                    cache[key] = (clock(), found)
                    return [dict(hit) for hit in found]
                failures.append(f"{name} returned no relevant readable search results")
        raise LocalSearchError("; ".join(failures) or "no search providers configured")

    return search
