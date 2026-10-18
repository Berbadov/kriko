"""Finding the local model server, and what it serves (B171).

The reader runs some program that serves a model over the OpenAI-compatible
protocol: Ollama, LM Studio, llama-server. Which one, on which port, with
which models downloaded, is a fact about their machine, so it is asked of the
machine and never typed into this file. `GET <base>/v1/models` is the question
every one of them answers, and the answer is the model list, verbatim.

The conventional loopback addresses below are engineering defaults of
those programs, a small closed vocabulary like the fuel types of the catalog:
they say where to *look*, not what exists. A reader whose server is elsewhere
gives its address in Settings and that address is probed first.

Every probe has a short timeout and they run side by side, because the screen
that shows the result is not allowed to hang on a server that is not running,
which is the normal state of a machine that has not started one yet.
"""

import json
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from app.agentresources import slot
from app.providers import network

#: name, base address. Where to look, not what is there.
CANDIDATES = (
    ("Ollama", "http://127.0.0.1:11434"),
    ("LM Studio", "http://127.0.0.1:1234"),
    ("llama-server", "http://127.0.0.1:8080"),
    ("vLLM", "http://127.0.0.1:8000"),
)

PROBE_TIMEOUT = 1.0

#: How long to wait for a TCP connection to be *accepted*, before asking that
#: address the HTTP question. A model server that is running accepts in
#: microseconds; a port with nothing behind it does not, and the difference is
#: what a full `PROBE_TIMEOUT` is spent on. Measured on Windows: a connect to a
#: closed loopback port raised `ConnectionRefusedError` only after **2.0 s**, so
#: every dead candidate in `CANDIDATES` cost the whole probe deadline — 1.1 s
#: for `discover()`, paid by `tasks.default_plane` before *every* run on every
#: plane, and again by the readiness check and the run's own plan. A fifth of a
#: second is a hundred times what an accepted loopback connection needs, so
#: nothing that is really there is missed, and a scan costs
#: the slowest dead one instead of the deadline.
CONNECT_TIMEOUT = 0.2

#: `discover` and `search_answers` are asked more than once before a single run
#: starts: `tasks.default_plane` (the plane decision), `localplane.is_ready`
#: (`_use_local_ask`) and `tasks._local_plan` (the run's own plan) are three
#: separate questions with the same answer, and every screen that draws the
#: planes card asks again. Inside this window the answer cannot have changed in
#: a way a reader would notice — starting a server and pressing the refresh is
#: what `forget_discovery` is for — and the probes are loopback round trips.
DISCOVERY_TTL_S = 1.5

#: The self-hosted search service the local plane prefers when it answers.
SEARCH_DEFAULT_URL = "http://127.0.0.1:7000"


def base_of(url: str) -> str:
    """An address as the protocol's base: no trailing slash, no `/v1`."""
    return (url or "").strip().rstrip("/").removesuffix("/v1").rstrip("/")


def _listening(url: str) -> bool:
    """Whether anything accepts a TCP connection at this address.

    The cheap half of a probe, asked first and alone: a port with nothing
    behind it is answered in `CONNECT_TIMEOUT` rather than in the whole HTTP
    deadline (see `CONNECT_TIMEOUT`). A failure to resolve the name is the same
    answer as a refusal — nothing is there — and neither is an error, because a
    server that is not running is the normal state of a machine that has not
    started one yet.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not host:
        return False
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    try:
        with socket.create_connection((host, port), CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


#: The remembered answer to a discovery question, and when it was asked.
#: Keyed on everything that changes the answer, including `CANDIDATES` itself,
#: so a test that points discovery at stubs of its own is asked afresh.
_ANSWERS: dict[tuple, tuple[float, list]] = {}


def forget_discovery() -> None:
    """Ask the machine again rather than reusing the last answer.

    Called when the reader says something changed — the Local machine screen's
    check, a model pull, a settings write — because the cache exists only to
    stop one turn asking the same question three times.
    """
    _ANSWERS.clear()


def _fresh(key: tuple) -> list | None:
    hit = _ANSWERS.get(key)
    if hit is not None and time.monotonic() - hit[0] < DISCOVERY_TTL_S:
        return hit[1]
    return None


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

    The connection is asked for first and separately (`_listening`), so an
    address with nothing behind it costs `CONNECT_TIMEOUT` and not the whole
    HTTP deadline. An address that accepts but does not answer in `timeout` is
    still down: a server that is there but wedged is not a model server.
    """
    base = base_of(url)
    up = False
    try:
        with slot("probe", base, timeout=timeout * 2):
            if not _listening(base):
                return {"url": base, "up": False, "models": []}
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

    Each row: `{name, url, up, models}`. Probed side by side, and remembered
    for `DISCOVERY_TTL_S`: one turn asks this three times (the plane decision,
    the readiness gate, the run's own plan) and the answer is the same
    question each time.

    Rows are handed out as copies. `localplane.resolve` writes the detected
    runtime's name onto a row it chose, and a cached row that a caller may
    edit is a row the next caller reads wrong.
    """
    key = ("discover", tuple(CANDIDATES), base_of(configured), timeout)
    remembered = _fresh(key)
    if remembered is not None:
        return [dict(row) for row in remembered]
    rows = _probed(configured, timeout)
    if not any(row.get("busy") for row in rows):
        # A busy probe did not test the address, so it is not an answer about
        # it: remembering it would turn one contended moment into a plane that
        # claims to be down for the next second and a half.
        _ANSWERS[key] = (time.monotonic(), rows)
    return rows


def _probed(configured: str, timeout: float) -> list[dict]:
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
    """Whether OpenSERP's health endpoint says the local service is ready.

    Remembered for `DISCOVERY_TTL_S` like `discover`, and for the same reason:
    the readiness gate and the run's own plan ask it in the same breath.
    """
    base = base_of(url) or SEARCH_DEFAULT_URL
    key = ("search", base, timeout)
    remembered = _fresh(key)
    if remembered is not None:
        return bool(remembered)
    answer = _search_answers(base, timeout)
    _ANSWERS[key] = (time.monotonic(), [answer])
    return answer


def _search_answers(base: str, timeout: float) -> bool:
    if not _listening(base):
        return False
    reached, payload = _get(base + "/health", timeout, health=True)
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
