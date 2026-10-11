"""The local machine plane: is it ready, where, and with which model (B171).

One answer, asked by everything that needs it: the planes card, Settings, the
extension door, `default_backend`, and the run itself. A screen that said
"ready" while the run found no model is the drift this file exists to prevent,
so the run resolves its address and model through `resolve` too.

Ready means a model server answers *and* serves a chat model, and the local
search service answers. Model names come from the server; default selection
uses the smallest known chat model of at least 4B parameters. A model explicitly
selected by the reader remains selected when installed.
"""

import re

from app import prefs
from app.providers import local_discovery as discovery
from app.providers.local_inference import DEFAULT_TIMEOUT, runtime_incomplete

#: A server lists every model it holds, including ones that only embed text.
#: Such a model cannot answer a prompt, so it is never picked by default. The
#: substring is a closed engineering convention (every such model says it).
_NOT_A_CHAT_MODEL = "embed"

DEFAULT_CONTEXT = 4096
MIN_CONTEXT = 2048
MAX_CONTEXT = 32768


def stored(app_state_path=None) -> dict:
    """The four local preferences, empty where the reader set none."""
    empty = dict.fromkeys(prefs.LOCAL_KEYS, "")
    empty[prefs.LOCAL_CONTEXT] = str(DEFAULT_CONTEXT)
    empty[prefs.LOCAL_OUTPUT_LANGUAGE] = "auto"
    empty[prefs.LOCAL_SEARCH_LANGUAGE] = "en"
    if app_state_path is None:
        return empty
    from app.web import state

    try:
        conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001 - a preference is never why a run fails
        return empty
    try:
        return {key: prefs.read(conn).get(key, "") for key in prefs.LOCAL_KEYS}
    finally:
        conn.close()


def timeout_of(value: str) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return seconds if seconds > 0 else DEFAULT_TIMEOUT


def _context_tokens(value: str) -> int:
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT
    return tokens if MIN_CONTEXT <= tokens <= MAX_CONTEXT else DEFAULT_CONTEXT


def _parameter_size(name: str) -> float | None:
    """Read a model's parameter size from its tag, including Gemma E-tags."""
    folded = name.casefold()
    sizes = [
        float(size)
        for size in re.findall(r"(?:^|[-_:])(\d+(?:\.\d+)?)b(?:$|[-_:])", folded)
    ]
    sizes.extend(
        float(size) for size in re.findall(r"(?:^|[-_:])e([24])b(?:$|[-_:])", folded)
    )
    return max(sizes, default=None)


def _pick(models: list[str], wanted: str) -> str:
    if wanted in models and _NOT_A_CHAT_MODEL not in wanted.casefold():
        return wanted
    chat = [one for one in models if _NOT_A_CHAT_MODEL not in one.casefold()]
    capable = [(one, _parameter_size(one)) for one in chat]
    capable = [(one, size) for one, size in capable if size is not None and size >= 4]
    return min(capable, key=lambda item: item[1])[0] if capable else ""


def resolve(
    app_state_path=None,
    *,
    url: str = "",
    model: str = "",
    search_url: str = "",
    with_search: bool = True,
) -> dict:
    """Probe this machine and say what a local run would use.

    `url`, `model` and `search_url` are a run's own choices and win over the
    stored ones, which win over discovery. A `model` that the server does not
    list is not used, and the reason says what it lists instead: a name from
    another provider's namespace must not reach a server that would 404 it.
    """
    mine = stored(app_state_path)
    want_url = url.strip() or mine[prefs.LOCAL_URL]
    want_model = model.strip() or mine[prefs.LOCAL_MODEL]
    want_search = search_url.strip() or mine[prefs.LOCAL_SEARCH_URL]
    # Side by side: each probe can cost its whole timeout when nothing
    # listens, and the screen waits for the slowest rather than the sum.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        found = pool.submit(discovery.discover, want_url)
        asked = (
            pool.submit(discovery.search_answers, want_search) if with_search else None
        )
        servers = found.result()
        searching = asked.result() if asked is not None else False

    chosen: dict | None
    if want_url:
        chosen = servers[0]
    else:
        chosen = None
        for wanted in ("models", "up"):
            chosen = next(iter(s for s in servers if s[wanted]), None)
            if chosen:
                break

    search = {
        "search_kind": "openserp" if searching else "",
        "search_url": discovery.base_of(want_search) or discovery.SEARCH_DEFAULT_URL,
        "search_label": (
            "the search service on this machine"
            if searching
            else "no local search service"
        ),
    }
    out = {
        "servers": servers,
        "url": chosen["url"] if chosen else "",
        "name": chosen["name"] if chosen else "",
        "models": [
            one for one in chosen["models"] if _NOT_A_CHAT_MODEL not in one.casefold()
        ]
        if chosen
        else [],
        "all_models": chosen["models"] if chosen else [],
        "model": "",
        "timeout": timeout_of(mine[prefs.LOCAL_TIMEOUT]),
        "context_tokens": _context_tokens(mine[prefs.LOCAL_CONTEXT]),
        "output_language": mine[prefs.LOCAL_OUTPUT_LANGUAGE] or "auto",
        "search_language": mine[prefs.LOCAL_SEARCH_LANGUAGE] or "en",
        "runtime_options": {},
        "ready": False,
        "reason": "",
        "line": "",
        **search,
    }

    if chosen is None or not chosen["up"]:
        looked = ", ".join(f"{s['name']} at {s['url']}" for s in servers)
        out["reason"] = (
            f"Nothing answers at {want_url}. Start that server or correct the "
            "address in Settings, Local machine."
            if want_url
            else f"No local model server is running (looked for {looked}). Start "
            "Ollama, LM Studio or llama-server, then check again."
        )
    elif not chosen["models"]:
        out["reason"] = (
            f"{chosen['name']} is running at {chosen['url']} but no model is "
            "downloaded. Download one in that app, then check again."
        )
    elif want_model and want_model not in out["models"]:
        if want_model in chosen["models"]:
            out["reason"] = (
                f"{want_model!r} is an embedding model and cannot answer research prompts. "
                "Choose an installed chat model in Settings, Local machine."
            )
        else:
            out["reason"] = (
                f"{chosen['name']} at {chosen['url']} has no chat model named "
                f"{want_model!r}. It has: {', '.join(out['models'])}. Pick one "
                "in Settings, Local machine."
            )
    else:
        out["model"] = _pick(out["models"], want_model)
        if out["model"]:
            out["ready"] = True
        else:
            small = [
                one
                for one in out["models"]
                if _parameter_size(one) is not None and _parameter_size(one) < 4
            ]
            out["reason"] = (
                "Only local chat models smaller than 4B are available. Choose one "
                "explicitly in Settings, Local machine, or install a model of at "
                "least 4B parameters."
                if small
                else "No local chat model with a known size of at least 4B is available. "
                "Choose an installed chat model explicitly in Settings, Local machine."
            )
    # A server that lists models and answers /api/version can still have no
    # runner to start one with (an install that was interrupted). A call that
    # found that out has said so; until the install is repaired the plane is
    # not ready, and the reason says what to press instead of "Ready".
    broken = runtime_incomplete(out["url"]) if chosen else ""
    out["runtime_incomplete"] = bool(broken)
    if broken:
        out["ready"] = False
        out["reason"] = broken
    from app.localruntime import inspect, options

    out["runtime"] = inspect(out["url"], out["name"], out["model"], mine)
    if out["runtime"]["runtime"] == "Ollama":
        out["name"] = "Ollama"
        if chosen:
            chosen["name"] = "Ollama"
    # Ollama loads a model at 4096 tokens unless told otherwise, which left a
    # quick look room for two or three pages and cut the rest from the front.
    # The reader's own context setting still wins; this is only the default.
    runtime_prefs = {**mine, prefs.LOCAL_CONTEXT: str(out["context_tokens"])}
    out["runtime_options"] = (
        {"num_ctx": out["context_tokens"], **options(runtime_prefs)}
        if out["runtime"]["supported"]
        else {}
    )
    if out["ready"] and with_search and not searching:
        out["ready"] = False
        out["reason"] = (
            f"No local search service is answering at {search['search_url']}. "
            "Start OpenSERP or change the address in Settings, Local machine."
        )
    if not with_search:
        # Not asked, so not claimed: a readiness check that skipped the
        # search probe must not say which search is in use.
        out["search_kind"] = out["search_label"] = ""
    out["line"] = (
        f"Ready: {out['model']} on {out['name']} at {out['url']}"
        + (f"; search through {search['search_label']}." if with_search else ".")
        if out["ready"]
        else out["reason"]
    )
    # The keys the planes card has always carried.
    out["inference_url"] = out["url"]
    out["serp_url"] = search["search_url"]
    return out


def is_ready(app_state_path=None) -> bool:
    try:
        return bool(resolve(app_state_path, with_search=False)["ready"])
    except Exception:  # noqa: BLE001 - a gate answers no rather than crashing
        return False


def reader_chose_an_agent(app_state_path=None) -> bool:
    """Whether the reader picked a coding or API agent in Settings.

    A pick is a choice of plane: the local plane goes first only for a reader
    who has not said otherwise (B172).
    """
    if app_state_path is None:
        return False
    from app.web import state

    try:
        conn = state.connect(app_state_path)
    except Exception:  # noqa: BLE001
        return False
    try:
        return prefs.read(conn).get(prefs.HARNESS) not in ("", prefs.LOCAL_PICK)
    finally:
        conn.close()
