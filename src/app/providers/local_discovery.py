"""Finding the local model server, and what it serves (B171).

The reader runs some program that serves a model over the OpenAI-compatible
protocol: Ollama, LM Studio, llama-server. Which one, on which port, with
which models downloaded, is a fact about their machine, so it is asked of the
machine and never typed into this file. `GET <base>/v1/models` is the question
every one of them answers, and the answer is the model list, verbatim.

The three conventional loopback addresses below are engineering defaults of
those programs, a small closed vocabulary like the fuel types of the catalog:
they say where to *look*, not what exists. A reader whose server is elsewhere
gives its address in Settings and that address is probed first.

Every probe has a short timeout and they run side by side, because the screen
that shows the result is not allowed to hang on a server that is not running,
which is the normal state of a machine that has not started one yet.
"""

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.agentresources import slot
from app.providers import network

#: name, base address. Where to look, not what is there.
CANDIDATES = (
    ("Ollama", "http://127.0.0.1:11434"),
    ("LM Studio", "http://127.0.0.1:1234"),
    ("llama-server", "http://127.0.0.1:8080"),
)

PROBE_TIMEOUT = 1.0

#: The self-hosted search service the local plane prefers when it answers.
SEARCH_DEFAULT_URL = "http://127.0.0.1:7000"


def base_of(url: str) -> str:
    """An address as the protocol's base: no trailing slash, no `/v1`."""
    return (url or "").strip().rstrip("/").removesuffix("/v1").rstrip("/")


def _get(url: str, timeout: float, *, health: bool = False):
    """`(reached, payload)`. Reached means *something* answered over HTTP,
    including a 404, because a server that refuses one path is still up."""
    try:
        with network.urlopen(url, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        # OpenSERP may return 503 for partial engine degradation. Preserve its
        # health document, without accepting error documents as model lists.
        if not health or error.code != 503:
            return True, None
        raw = error.read(65536).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - a down server is an answer, not an error
        return False, None
    try:
        return True, json.loads(raw)
    except ValueError:
        return True, None


def _ids(payload) -> list[str] | None:
    """Model ids from an OpenAI-shaped list, or `None` if it is not one."""
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("models"))
    if not isinstance(payload, list):
        return None
    seen: list[str] = []
    for item in payload:
        name = item.get("id") or item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip() and name not in seen:
            seen.append(name)
    return seen


def probe(url: str, timeout: float = PROBE_TIMEOUT) -> dict:
    """What one address says: `{url, up, models}`.

    `/v1/models` first, `/models` for a server that mounts the list at its
    root. A server that answers neither with a list is up with no models,
    and the screen says so in those words.
    """
    base = base_of(url)
    up = False
    try:
        with slot("probe", base, timeout=timeout * 2):
            for path in ("/v1/models", "/models"):
                reached, payload = _get(base + path, timeout)
                up = up or reached
                models = _ids(payload)
                if models is not None:
                    return {"url": base, "up": True, "models": models}
                if not reached:
                    break  # nothing listens here; the second path cannot differ
    except TimeoutError:
        # CLI capability checks and other screens share this capacity. A busy
        # host has not tested this address; it must not fail the whole screen
        # or claim the server is down. A later refresh can probe it again.
        return {"url": base, "up": False, "models": [], "busy": True}
    return {"url": base, "up": up, "models": []}


def discover(configured: str = "", timeout: float = PROBE_TIMEOUT) -> list[dict]:
    """Every server that could be the one, configured address first.

    Each row: `{name, url, up, models}`. Probed side by side.
    """
    # url -> name, configured first. A configured address that is one of the
    # conventional ones keeps the program's own name, which is what the
    # reader knows it by.
    names = dict((url, name) for name, url in CANDIDATES)
    own = base_of(configured)
    order = ([own] if own else []) + [url for _, url in CANDIDATES if url != own]
    wanted = [(names.get(url, "configured"), url) for url in order]
    with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        found = list(pool.map(lambda one: probe(one[1], timeout), wanted))
    return [{"name": name, **row} for (name, _), row in zip(wanted, found)]


def search_answers(url: str = "", timeout: float = PROBE_TIMEOUT) -> bool:
    """Whether OpenSERP's health endpoint says the local service is ready."""
    reached, payload = _get((base_of(url) or SEARCH_DEFAULT_URL) + "/health", timeout,
                            health=True)
    engines = payload.get("engines") if isinstance(payload, dict) else []
    if not isinstance(engines, list):
        engines = []
    return bool(
        reached
        and isinstance(payload, dict)
        and (payload.get("status") in ("healthy", "ok") or payload.get("ok") is True
             or (payload.get("status") == "degraded"
                 and any(isinstance(engine, dict)
                         and engine.get("name") in ("google", "bing", "duckduckgo")
                         and engine.get("initialized") is True
                         and engine.get("status") == "ready"
                         for engine in engines)))
    )
