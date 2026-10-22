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
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any
from app.providers import network

from app.providers._http import TIMEOUT
from kriko.research.politeness import LocalSearchError

DEFAULT_BASE_URL = "http://127.0.0.1:7000"
DEFAULT_ENGINE = "duckduckgo"
MAX_SEARCH_BYTES = 4_000_000


def _response_body(response, deadline: float, check) -> bytes:
    """Poll cancellation between available HTTP chunks, including trickled bodies."""
    read_chunk = getattr(response, "read1", None)
    if not callable(read_chunk):
        # Simple injected responses may expose only a whole-body read. urllib's
        # HTTPResponse has read1, which returns available bytes without waiting
        # for an entire large buffer to fill.
        check()
        body = response.read()
        check()
        if len(body) > MAX_SEARCH_BYTES or time.monotonic() >= deadline:
            raise LocalSearchError("search response exceeded its size or time budget")
        return body
    parts: list[bytes] = []
    size = 0
    while True:
        check()
        if time.monotonic() >= deadline:
            raise LocalSearchError("search response budget reached")
        chunk = read_chunk(min(65536, MAX_SEARCH_BYTES + 1 - size))
        if not chunk:
            return b"".join(parts)
        size += len(chunk)
        if size > MAX_SEARCH_BYTES:
            raise LocalSearchError("search response was too large")
        parts.append(chunk)

#: The engines a local run asks together. Measured on this service, one engine
#: at a time: Google answered 6 of 6 (9 hits, 5-6 s) while two others had
#: their breakers open; DuckDuckGo times out on some queries; several engines at
#: once, because a search answers with what any of them found.
#:
#: Bing is gone. It answered `"WH-1000XM4 headphones" owner reports forum` with
#: WhatsApp and grammar pages, and on a look whose search it won that was nine
#: unreadable pages and no findings. `carries_name` now refuses an answer that
#: does not name the quoted product, which catches that class whatever engine
#: produces it; Bing is removed anyway because a wrong answer that passes for a
#: right one is not worth the risk, and two engines still answer together.
LOCAL_ENGINES = "google,duckduckgo"

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


#: A quick-look query names the product inside double quotes
#: (`"WH-1000XM4 headphones" owner reports forum`). Those words are the least
#: an answer has to contain to be about the same thing.
_QUOTED_NAME = re.compile(r'"([^"]{3,})"')
_NAME_TERM = re.compile(r"[^\W_]{4,}")


def carries_name(hits: list[dict], query: str) -> bool:
    """Whether an engine's answer is about the product the query names.

    The per-engine fast path returns the first engine that answers, which
    rewards speed over correctness: measured, Bing answered a quoted Sony
    model with WhatsApp and grammar pages while Google and DuckDuckGo returned
    headphones, and Bing won the race. So an answer whose titles and addresses
    share no word with the quoted name waits instead of being taken.

    No engine is named here; the rule is about the answer. A query with no
    quoted name is not judged, and a named answer is still preferred even when
    it is the only one (`searcher` falls back to it), because a weak page is
    what the reader already had before this rule existed.
    """
    phrase = _QUOTED_NAME.search(query or "")
    if phrase is None:
        return True
    wanted = {term.casefold() for term in _NAME_TERM.findall(phrase.group(1))}
    if not wanted:
        return True
    seen = " ".join(
        f"{hit.get('title') or ''} {hit.get('url') or ''}"
        for hit in hits if isinstance(hit, dict)).casefold()
    return any(term in seen for term in wanted)


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report a redirect instead of following it: the address is the answer."""

    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


_NO_REDIRECT = urllib.request.build_opener(_NoRedirect)
USER_AGENT = "Kriko/1.0 (+https://github.com/Berbadov/kriko)"


def _is_google_goto(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return ((parsed.hostname or "").casefold() in {"google.com", "www.google.com"}
            and parsed.path.casefold().rstrip("/") == "/goto")


def unwrap_goto(url: str, *, check=None, timeout: float = 6.0) -> str:
    """The page behind a Google click-through link, or "" when it will not say.

    The link carries an opaque token and no address, so it was dropped on the
    belief that it "can neither be read nor unwrapped". It can: Google answers
    it with a plain 302 whose `Location` is the page, and Google was the one
    engine answering every query when the others timed out or came back empty
    (measured: titles such as "Crucial MX500 SSDs world of pain" behind links
    the adapter threw away). One request, redirect not followed; the page
    itself is read later by the reader as any other.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def opener(target, timeout=None):
        return _NO_REDIRECT.open(target, timeout=timeout)

    try:
        with network.urlopen(request, timeout=timeout, opener=opener, check=check):
            return ""  # answered with a page, not a redirect: nothing to unwrap
    except urllib.error.HTTPError as error:
        location = (error.headers.get("Location") or "").strip() if error.headers else ""
        if error.code in (301, 302, 303, 307, 308) and location.lower().startswith(
                ("http://", "https://")) and not _is_google_goto(location):
            return location
        return ""
    except Exception:  # noqa: BLE001 - an unwrappable link is dropped, as before
        return ""


def _unwrapped(results: list, check=None, resolve=None) -> list:
    """`results` with each Google click-through replaced by the page it names."""
    resolve = resolve or unwrap_goto
    wrapped = [index for index, hit in enumerate(results)
               if isinstance(hit, dict) and _is_google_goto(str(hit.get("url", "")))]
    if not wrapped:
        return results
    with ThreadPoolExecutor(max_workers=min(4, len(wrapped))) as pool:
        opened = list(pool.map(lambda index: resolve(str(results[index]["url"]),
                                                     check=check), wrapped))
    out = list(results)
    for index, address in zip(wrapped, opened):
        # The engine's `domain` named Google, the page's host is the site.
        out[index] = {**results[index], "url": address, "domain": ""}
    return out


def searcher(base_url: str = "", engine: str = "", *, language: str = "en",
             resolve=None, timeout: float = TIMEOUT, mode: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`.

    Same injected shape as the paid plane's search sockets, so the local
    plane is wired exactly like the paid one and the engine never learns
    which kind of searcher it was handed.
    """
    endpoint = (base_url or DEFAULT_BASE_URL).rstrip("/")
    chosen = engine or DEFAULT_ENGINE
    default_mode = mode
    stats = {"queries": 0, "hits": 0, "challenges": 0}
    stats_lock = threading.Lock()

    def search(query: str, limit: int = 5, *, timeout: float | None = None,
               pace_interval: float | None = None, mode: str | None = None,
               engines: str = "") -> list[dict]:
        request_mode = mode or default_mode
        total_timeout = timeout if timeout is not None else search_timeout
        engine_names = _engines_to_ask(engines or chosen).split(",")
        # In `any` mode use the selected engines' own endpoints. Mega
        # counts a Google click-through as a result before this adapter can
        # reject it, so the next engine must get a chance to return a page.
        per_engine = request_mode == "any"
        routes = engine_names if per_engine else [""]
        deadline = time.monotonic() + total_timeout if per_engine else 0.0
        last_error: Exception | None = None
        had_response = False
        check_cancelled = getattr(search, "check_cancelled", None)
        callback_error: BaseException | None = None
        start_pace = pace_interval if pace_interval is not None else 0.25

        if per_engine and len(engine_names) > 1:
            # A slow first engine must not consume the whole interactive
            # budget before the next engine gets a chance. Each selected
            # engine receives this query once; outbound pacing still applies.
            if check_cancelled is not None:
                check_cancelled()
            stop = threading.Event()

            def check_worker() -> None:
                if stop.is_set() or time.monotonic() >= deadline:
                    raise LocalSearchError("search stopped")

            def one_engine(name: str) -> list[dict]:
                child = searcher(endpoint, engine=name, language=language,
                                 timeout=total_timeout, mode="any", resolve=resolve)
                child.check_cancelled = check_worker
                try:
                    check_worker()
                    return child(query, limit, timeout=max(0.001, deadline - time.monotonic()),
                                 pace_interval=start_pace)
                finally:
                    with stats_lock:
                        for key in stats:
                            stats[key] += child.stats[key]

            pool = ThreadPoolExecutor(max_workers=min(3, len(engine_names)),
                                      thread_name_prefix="kriko-search")
            jobs = {pool.submit(one_engine, name): index
                    for index, name in enumerate(engine_names)}
            pending = set(jobs)
            failures: list[Exception] = []
            answered = False
            # An answer that is not about the named product, kept only if no
            # engine produces one that is (see `carries_name`).
            fallback: list[dict] = []
            try:
                while pending and time.monotonic() < deadline:
                    if check_cancelled is not None:
                        check_cancelled()
                    done, pending = wait(pending, timeout=min(0.05, max(0.0, deadline - time.monotonic())),
                                         return_when=FIRST_COMPLETED)
                    for future in sorted(done, key=jobs.__getitem__):
                        try:
                            hits = future.result()
                        except LocalSearchError as error:
                            failures.append(error)
                            continue
                        answered = True
                        if hits:
                            if carries_name(hits, query):
                                return hits
                            fallback = fallback or hits
                if check_cancelled is not None:
                    check_cancelled()
                if not answered and failures and not pending:
                    raise LocalSearchError(str(failures[-1])) from failures[-1]
                if pending and not answered:
                    raise LocalSearchError("search engines did not answer within the time budget")
                return fallback
            finally:
                stop.set()
                pool.shutdown(wait=False, cancel_futures=True)

        def check_request() -> None:
            nonlocal callback_error
            if check_cancelled is None:
                return
            try:
                check_cancelled()
            except BaseException as error:
                callback_error = error
                raise

        for engine_name in routes:
            if per_engine:
                request_timeout = deadline - time.monotonic()
                if request_timeout <= 0:
                    break
                engine_path = "duck" if engine_name == "duckduckgo" else engine_name
                path = f"{engine_path}/search"
                params = {"text": query, "limit": max(1, int(limit)),
                          "format": "json", "lang": language}
            else:
                request_timeout = total_timeout
                path = "mega/search"
                params = {"text": query, "engines": ",".join(engine_names),
                          "limit": max(1, int(limit)), "format": "json",
                          "lang": language}
                if request_mode:
                    params["mode"] = request_mode
            request = urllib.request.Request(
                f"{endpoint}/{path}?{urllib.parse.urlencode(params)}",
                headers={"Accept": "application/json"},
            )
            try:
                request_ends = time.monotonic() + request_timeout
                options: dict[str, Any] = {"check": check_request} if check_cancelled is not None else {}
                with network.urlopen(request, timeout=request_timeout,
                                     pace_interval=start_pace, **options) as response:
                    body = _response_body(response, request_ends, check_request).decode("utf-8", "replace")
            except Exception as error:  # noqa: BLE001 — network, rotate
                if callback_error is not None:
                    raise callback_error
                last_error = error
                if per_engine:
                    continue
                raise LocalSearchError(str(error)) from error
            with stats_lock:
                stats["queries"] += 1
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as error:
                challenge = any(marker in body[:4096].casefold()
                                for marker in _BLOCK_MARKERS)
                if challenge:
                    with stats_lock:
                        stats["challenges"] += 1
                last_error = LocalSearchError(
                    "the SERP answered with a challenge page" if challenge
                    else "the SERP did not answer with JSON")
                if per_engine:
                    continue
                raise last_error from error
            _note_failed_engines(payload)
            results = payload.get("results") if isinstance(payload, dict) else []
            if not isinstance(results, list):
                last_error = LocalSearchError("the SERP returned an invalid results array")
                if per_engine:
                    continue
                raise last_error
            if not results and isinstance(payload, dict):
                message = str(payload.get("error") or payload.get("message") or "")
                challenge = any(marker in message.casefold() for marker in _BLOCK_MARKERS)
                if challenge:
                    with stats_lock:
                        stats["challenges"] += 1
                if challenge or payload.get("error"):
                    last_error = LocalSearchError(
                        "the SERP answered with a challenge" if challenge
                        else message[:250])
                    if per_engine:
                        continue
                    raise last_error
            had_response = True
            # Fast searches need the same destination resolution as research.
            # Google often returns only /goto links; dropping them made a
            # working engine look as though it found nothing.
            resolver = resolve
            if per_engine and resolver is None:
                def resolver(address, *, check=None):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return ""
                    return unwrap_goto(address, check=check, timeout=min(2.0, remaining))
            candidates = _unwrapped(results, check_cancelled, resolver)
            out = []
            for hit in candidates:
                if not isinstance(hit, dict):
                    continue
                url = str(hit.get("url", "")).strip()
                if not url or _is_ad_or_search_redirect(url, hit.get("type")):
                    continue
                try:
                    parsed = urllib.parse.urlsplit(url)
                except ValueError:
                    continue
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    continue
                site = str(hit.get("domain", "")).strip()
                if not site:
                    netloc = urllib.parse.urlsplit(url).netloc
                    site = netloc.split("@")[-1].split(":")[0]
                item = {"url": url, "title": str(hit.get("title", "")).strip(), "site": site}
                if hit.get("snippet"):
                    item["snippet"] = str(hit["snippet"])[:1000]
                out.append(item)
                if len(out) >= max(1, int(limit)):
                    break
            with stats_lock:
                stats["hits"] += len(out)
            if out or not per_engine:
                return out

        if per_engine and not had_response and last_error is not None:
            raise LocalSearchError(str(last_error)) from last_error
        return []

    search_timeout = timeout
    #: What a caller may aim one query at. `engines=` on a call asks just those,
    #: so several queries can run at once with no engine asked by two.
    search.engines = [name.strip() for name in chosen.split(",")  # type: ignore[attr-defined]
                      if name.strip()]
    search.stats = stats  # type: ignore[attr-defined]
    search.check_cancelled = None  # type: ignore[attr-defined]
    search.supports_timeout = True  # type: ignore[attr-defined]
    #: The longest this searcher would wait on its own. A chain above it uses
    #: this as the ceiling for one query, so its own deadline never hands this
    #: adapter a longer leash than it was built with.
    search.default_timeout = float(search_timeout)  # type: ignore[attr-defined]
    search.supports_pacing = True  # type: ignore[attr-defined]
    search.supports_fast_options = True  # type: ignore[attr-defined]
    return search
