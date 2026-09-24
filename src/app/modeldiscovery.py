"""Which LLMs each keyed completion provider offers today — asked, not written.

`modelcatalogue.offered` has always taken a `discovered` mapping and nothing
ever passed one, so the paid plane's list was the shipped `models.toml` and
nothing else: a model released after the file was written was unselectable
until a release of ours, which is the list-in-the-code failure the harness
plane had with `claude`'s aliases.

`GET /models` answers with ids and nothing else, which is why the catalogue
stays (it is what a model *costs*). This module is the other half.

Two rules, both from the screen that reads it:

* **A settings page never waits on the network.** `cached()` returns what is
  known and starts a background refresh when that is stale; only `fresh`
  (the Re-ask button) blocks, because then the reader asked for exactly that.
* **A failure is a smaller list, never an error.** No key, a gateway with no
  `/models`, a timeout — each reads as "nothing discovered" for that provider.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

#: A provider's model list changes on the order of weeks. An hour keeps a
#: new release a restart-free hour away without asking on every page load.
TTL = 3600.0
_TTL_FAILED = 300.0
TIMEOUT = 8.0

_CACHE: dict[str, tuple[float, list[str]]] = {}
_LOCK = threading.Lock()
_REFRESHING = threading.Event()


def _request(provider_id: str, key: str) -> urllib.request.Request:
    if provider_id == "anthropic":
        from app.providers import anthropic_llm

        base = os.environ.get("ANTHROPIC_BASE_URL") or anthropic_llm.DEFAULT_BASE_URL
        headers = {"x-api-key": key, "anthropic-version": anthropic_llm.API_VERSION}
    else:
        from app.providers import llm

        base = os.environ.get("LLM_BASE_URL") or llm.DEFAULT_BASE_URL
        headers = {"authorization": f"Bearer {key}"}
    return urllib.request.Request(base.rstrip("/") + "/models?limit=1000", headers=headers)


def ask(provider_id: str, opener=urllib.request.urlopen) -> list[str]:
    """One provider's ids, or `[]`. `opener` is the test seam."""
    from app import keys
    from app.providers import MissingKey

    try:
        key = keys.require(provider_id)
    except MissingKey:
        return []
    try:
        with opener(_request(provider_id, key), timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8", "replace")) or {}
    except urllib.error.HTTPError as error:
        # The status is safe to log; the body may quote the request.
        log.info("%s /models answered HTTP %s", provider_id, error.code)
        return []
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        log.info("%s /models unreachable: %s", provider_id, type(error).__name__)
        return []
    out: list[str] = []
    rows = (body.get("data") or []) if isinstance(body, dict) else []
    for row in rows if isinstance(rows, list) else []:
        name = str((row or {}).get("id") or "").strip() if isinstance(row, dict) else ""
        if name and name not in out:
            out.append(name)
    return out


def _providers() -> list[str]:
    from app import keys

    present = {one["id"] for one in keys.status() if one["present"]}
    return [one for one in keys.COMPLETION_PROVIDERS if one in present]


def refresh() -> dict[str, list[str]]:
    """Ask every keyed provider now, concurrently, and remember the answers."""
    from concurrent.futures import ThreadPoolExecutor

    wanted = _providers()
    if not wanted:
        return {}
    with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        found = dict(zip(wanted, pool.map(ask, wanted), strict=True))
    now = time.monotonic()
    with _LOCK:
        for provider_id, names in found.items():
            _CACHE[provider_id] = (now, names)
    return found


def _refresh_in_background() -> None:
    if _REFRESHING.is_set():
        return
    _REFRESHING.set()

    def run():
        try:
            refresh()
        except Exception:  # noqa: BLE001 — a model list is never worth a crash
            log.warning("could not refresh the provider model lists", exc_info=True)
        finally:
            _REFRESHING.clear()

    threading.Thread(target=run, name="kriko-model-discovery", daemon=True).start()


def cached(*, fresh: bool = False) -> dict[str, list[str]]:
    """What each keyed provider was last known to offer.

    `fresh` asks now and waits. Otherwise this never blocks: anything missing
    or stale is refreshed in the background and shows up on the next read.
    """
    if fresh:
        return refresh()
    wanted = _providers()
    now = time.monotonic()
    out: dict[str, list[str]] = {}
    stale = False
    with _LOCK:
        for provider_id in wanted:
            hit = _CACHE.get(provider_id)
            if hit is None:
                stale = True
                continue
            at, names = hit
            out[provider_id] = list(names)
            if now - at >= (TTL if names else _TTL_FAILED):
                stale = True
    if stale:
        _refresh_in_background()
    return out
