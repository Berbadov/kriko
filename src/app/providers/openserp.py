"""Search through a self-hosted SERP service.

OpenSERP is the reference target: a single native binary serving
`/mega/search` and per-engine endpoints on localhost, no container, no key.
The wire shape is deliberately thin — one GET, JSON out — and exactly
OpenSERP's: `GET /mega/search?text=...&engines=...&limit=...` answered with
`results: [{url, title, domain}]`. Another SERP works only if it serves that
same path and shape; SearXNG, for one, does not (it answers `/search?q=`).
If OpenSERP is unavailable, the local plane reports that it cannot search;
it does not send queries to a hosted provider.

What this adapter adds over pointing the paid plane's Exa socket at a
localhost URL is the failure contract: a SERP that answers with a challenge
page is *not* a result set, and `LocalSearchError` is what tells the plane's
politeness scheduler to mark the source hot and rotate — the fail-fast rule
the reader set: never wait on a challenge, move to the next engine.

Politeness lives in the scheduler, not here. This adapter does one query at
a time and reports what it saw; pacing, rotation and cooldown are the
scheduler's to enforce, in one place.
"""

import json
import threading
import time
import urllib.parse
import urllib.request
from app.providers import network

from app.providers._http import TIMEOUT
from kriko.research.politeness import LocalSearchError

DEFAULT_BASE_URL = "http://127.0.0.1:7000"
DEFAULT_ENGINE = "duckduckgo"

#: `/mega/search` waits for its slowest engine, so one blocked engine costs
#: every query the time it takes to fail (measured: Ecosia blocked, Baidu 36 s
#: to a 502, Yandex a captcha, against 2-6 s for the engines that answered).
#: The service names the engines that failed (`meta.engines_failed`); those
#: are left out of the next queries for this long and then tried again, so a
#: block that lifts is noticed. Taken from what the service reports, never a
#: list of bad engines typed here.
ENGINE_COOLDOWN_SECONDS = 600.0
_failed_at: dict[str, float] = {}
_failed_lock = threading.Lock()


def _engines_to_ask(requested: str) -> str:
    """`requested` without the engines that failed recently, never empty."""
    names = [name.strip() for name in requested.split(",") if name.strip()]
    now = time.monotonic()
    with _failed_lock:
        live = [name for name in names
                if name not in _failed_at
                or now - _failed_at[name] >= ENGINE_COOLDOWN_SECONDS]
    return ",".join(live or names)


def _note_failed_engines(payload: object) -> None:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    failed = meta.get("engines_failed") if isinstance(meta, dict) else None
    if not isinstance(failed, list):
        return
    now = time.monotonic()
    with _failed_lock:
        for name in failed:
            if isinstance(name, str) and name:
                _failed_at[name] = now

#: Same markers the politeness module reads, checked here because the SERP
#: itself is the first thing a challenge hits — a block page that reaches
#: the plane as a "result set" would be a block page the scheduler never
#: hears about.
_BLOCK_MARKERS = (
    "captcha",
    "challenge",
    "unusual traffic",
    "are you a robot",
    "access denied",
    "blocked",
    "attention required",
)


def _is_ad_or_search_redirect(url: str, result_type: object = "") -> bool:
    """Reject sponsored entries and search-engine click-through URLs.

    OpenSERP's mega response includes richer fields such as ``type`` even
    though this adapter only exposes the compact result shape to the reader.
    Keep the URL checks too: some engine/version combinations omit that
    metadata while still returning their own ad redirect URL.
    """
    kind = str(result_type or "").strip().casefold().replace("_", "-")
    if kind in {"ad", "ads", "advertisement", "sponsored", "paid"}:
        return True

    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return False

    path = parsed.path.casefold().rstrip("/")
    # These endpoints are click trackers, not destination pages. Match the
    # host and path together so ordinary pages with the same path stay valid.
    if host == "duckduckgo.com" and path == "/y.js":
        return True
    if host == "bing.com" and path == "/aclick":
        return True
    if host in {"google.com", "www.google.com", "google.fr"} and path == "/aclk":
        return True
    # Google's own click-through with an opaque token (no destination in it),
    # so it can neither be read nor unwrapped; the same result usually
    # arrives from another engine under its real address.
    if host in {"google.com", "www.google.com"} and path == "/goto":
        return True
    return False


def searcher(base_url: str = "", engine: str = "", *, language: str = "en"):
    """`search(query, limit) -> [{"url", "title", "site"}]`.

    Same injected shape as the paid plane's search sockets, so the local
    plane is wired exactly like the paid one and the engine never learns
    which kind of searcher it was handed.
    """
    endpoint = (base_url or DEFAULT_BASE_URL).rstrip("/")
    chosen = engine or DEFAULT_ENGINE
    stats = {"queries": 0, "hits": 0, "challenges": 0}

    def search(query: str, limit: int = 5) -> list[dict]:
        params = urllib.parse.urlencode(
            {
                "text": query,
                "engines": _engines_to_ask(chosen),
                "limit": max(1, int(limit)),
                "format": "json",
                "lang": language,
            }
        )
        request = urllib.request.Request(
            f"{endpoint}/mega/search?{params}",
            headers={"Accept": "application/json"},
        )
        try:
            check_cancelled = getattr(search, "check_cancelled", None)
            with network.urlopen(request, timeout=TIMEOUT,
                                 pace_interval=0.25,
                                 check=check_cancelled) as response:
                body = response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001 — network, rotate
            raise LocalSearchError(str(error)) from error
        stats["queries"] += 1
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            if any(marker in body[:4096].casefold() for marker in _BLOCK_MARKERS):
                stats["challenges"] += 1
                raise LocalSearchError(
                    "the SERP answered with a challenge page"
                ) from error
            raise LocalSearchError("the SERP did not answer with JSON") from error
        _note_failed_engines(payload)
        results = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(results, list):
            raise LocalSearchError("the SERP returned an invalid results array")
        if not results and isinstance(payload, dict):
            message = str(payload.get("error") or payload.get("message") or "")
            if any(marker in message.casefold() for marker in _BLOCK_MARKERS):
                stats["challenges"] += 1
                raise LocalSearchError("the SERP answered with a challenge")
            if payload.get("error"):
                raise LocalSearchError(message[:250])
        out = []
        for hit in results or []:
            if not isinstance(hit, dict):
                continue
            url = str(hit.get("url", "")).strip()
            if not url or _is_ad_or_search_redirect(url, hit.get("type")):
                continue
            site = str(hit.get("domain", "")).strip()
            if not site:
                netloc = urllib.parse.urlsplit(url).netloc
                site = netloc.split("@")[-1].split(":")[0]
            out.append(
                {
                    "url": url,
                    "title": str(hit.get("title", "")).strip(),
                    "site": site,
                }
            )
        stats["hits"] += len(out)
        return out

    search.stats = stats  # type: ignore[attr-defined]
    search.check_cancelled = None  # type: ignore[attr-defined]
    return search
