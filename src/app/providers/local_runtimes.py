"""The programs a local model can be served by, and a check of one address.

Settings lets the reader say which program the local agent talks to and where
it listens, then press Check to see that it answers and which models it lists.
Everything here is read from what the app already knows:

* the conventional programs and their loopback addresses are
  `local_discovery.CANDIDATES` (where discovery already looks);
* which of them is Ollama, and what Kriko can set on it, is
  `localruntime.inspect` (it asks `/api/version` and `/api/ps`);
* what to run for vLLM on this machine is `vllmplan.plan`, drawn by the Local
  screen from `/api/machine`, which the check points to rather than copying.

A runtime pick is only a pre-filled address plus a label: all of them speak the
same OpenAI-compatible protocol, which is what the local plane uses, so
"any OpenAI-compatible endpoint" is the same thing with the address typed in.

**Kriko installs none of them.** Starting or installing a model server is the
reader's press, on the Local screen, and never a side effect of choosing one
here.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.providers import local_discovery

#: Written to the runtime setting for "any server that speaks the protocol".
CUSTOM = "custom"

#: How the programs name themselves to the reader, where the discovery's own
#: label is a command name rather than a product. Spelling aliases only.
_LABELS = {"llama-server": "llama.cpp server"}

#: What to do when nothing answers, by program: where its server is started.
_START = {
    "ollama": "Start Ollama (its tray icon, or `ollama serve`).",
    "lm-studio": "In LM Studio, open the Developer tab and start the server.",
    "llama-server": "Start `llama-server` with a model, for example `llama-server -m model.gguf`.",
    "vllm": "Start `vllm serve <model>`; the Local screen shows the steps for this computer.",
}


def _slug(name: str) -> str:
    return "-".join(name.casefold().split())


def runtimes() -> list[dict]:
    """`[{id, name, url}]` in discovery's order, then the typed-in endpoint."""
    rows = [{"id": _slug(name), "name": _LABELS.get(name, name), "url": url}
            for name, url in local_discovery.CANDIDATES]
    rows.append({"id": CUSTOM, "name": "Any OpenAI-compatible endpoint", "url": ""})
    return rows


def default_url(runtime: str) -> str:
    return next((row["url"] for row in runtimes() if row["id"] == runtime), "")


def valid_address(url: str) -> str:
    """`url` as a base address, or "" when it is not an http(s) address without credentials."""
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
        ok = (parts.scheme in ("http", "https") and bool(parts.hostname)
              and not parts.username and not parts.password
              and not parts.query and not parts.fragment)
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return ""
    return local_discovery.base_of(text) if ok else ""


def check(url: str, runtime: str = "", mine: dict | None = None) -> dict:
    """Ask one address whether it answers, and what it lists.

    `{url, up, models, detected, message, loader}`. `message` says what to do
    next in the reader's terms; it never reads as an error code. The address is
    the reader's own, typed into their own Settings.
    """
    from app import localruntime

    base = valid_address(url) or valid_address(default_url(runtime))
    if not base:
        return {"url": "", "up": False, "models": [], "detected": "", "loader": None,
                "message": "Type the address the server listens on, for example "
                           "http://127.0.0.1:1234."}
    row = local_discovery.probe(base)
    models = list(row.get("models") or [])
    detected = ""
    loader = None
    if row.get("up"):
        info = localruntime.inspect(base, "configured", "", mine or {})
        detected = "Ollama" if info.get("runtime") == "Ollama" else "OpenAI-compatible server"
        loader = {"supported": bool(info.get("supported")), "help": info.get("settings_help", "")}
    name = next((one["name"] for one in runtimes() if one["id"] == runtime), "The server")
    if row.get("busy"):
        message = "This computer is busy checking other servers. Check again in a moment."
    elif not row.get("up"):
        hint = _START.get(runtime, "Start the server, or correct the address.")
        message = f"Nothing answers at {base}. {hint}"
    elif not models:
        message = (f"{name} answers at {base} but lists no models. "
                   "Download one in that program, then check again.")
    else:
        count = len(models)
        message = f"{name} answers at {base} and lists {count} model{'s' if count != 1 else ''}."
        if runtime == "ollama" and detected != "Ollama":
            message += " It does not answer like Ollama, so Kriko will treat it as a generic server."
    return {"url": base, "up": bool(row.get("up")), "models": models,
            "detected": detected, "message": message, "loader": loader,
            "busy": bool(row.get("busy"))}
