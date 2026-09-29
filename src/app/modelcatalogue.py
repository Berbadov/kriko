"""Which models this installation can use, what they cost, and whether they work.

The reader asked to choose the model, and to be shown what they need to decide:
context window, price, rough speed, and whether it is usable on their key at
all — *with the reason* when it is not, rather than greyed out in silence or
failing at runtime four minutes into a run.

Three sources, merged, and the split matters:

**The catalogue** (`models.toml`) is what a model *costs and can read*. It is
copied to `~/.kriko/models.toml` on first run and never written again, so the
reader's edits survive updates. Prices change and gateways charge differently;
a number compiled into the program is wrong the day after it ships and nobody
can correct it. This is the same file `app/costs.py`'s meter prices a run from,
deliberately — two tables would disagree, and the one the reader edited would
be the one that lost.

**Discovery** is what an endpoint actually offers today. `GET /v1/models`
returns ids and nothing else — no price, no context window — which is exactly
why the catalogue cannot be replaced by it. Merged in so a model released after
this file was written is selectable the day it exists.

**Keys** are whether it can be used at all. A provider with no key is not
hidden: it is listed, unusable, with the reason, because "why can I not pick
Opus" has an answer and hiding the row withholds it.

Nothing here is a fixed list of *what is good*. Which model suits extraction
versus synthesis is the reader's call, and the roles below are named stages of
a run, not a ranking.
"""

import tomllib
from pathlib import Path

#: The stages of a run that may each take their own model.
#:
#: Named for what they *do*, because the reason to split them is economic and
#: it only reads if the stages do different work: extraction is bulk
#: transcription over many documents and a cheap model is often right for it,
#: while synthesis happens once and is where being wrong costs the most. One
#: dropdown per stage would be a wall of them for a first-time reader, so this
#: is an advanced control and every role falls back to the single default.
ROLES = ("plan", "extract", "synthesise", "validate")
ACTIVE_ROLES = ("extract",)

#: What each role is for, in the reader's terms. Shipped with the roles rather
#: than written in the client, so the two cannot drift apart.
ROLE_NOTES = {
    "plan": "works out what to search for",
    "extract": "reads each source and pulls findings out — the bulk of the work",
    "synthesise": "turns findings into what the reader sees",
    "validate": "checks the result against the pack's bar",
}

#: Where a reader's own copy lives. Beside the store rather than inside it: a
#: price list is interface state, and editing it must not change any pack's
#: `content_digest`.
FILENAME = "models.toml"


def default_path() -> Path:
    return Path(__file__).resolve().parent / FILENAME


def catalogue_path(home: Path) -> Path:
    return Path(home) / FILENAME


def install_default(home: Path) -> Path:
    """Put the shipped catalogue in the reader's home, once, and never again.

    Never overwrites. An update that replaced this file would silently discard
    a reader's corrected prices, and they would not find out until a cost
    report was wrong.
    """
    target = catalogue_path(home)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(default_path().read_bytes())
    return target


#: The table in `models.toml` that prices tools rather than models. Skipped by
#: `load`, read by `tool_price`.
TOOLS = "tools"


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load(home: Path | None = None) -> dict[str, dict]:
    """`model id -> row`: the reader's catalogue, over the shipped one.

    **Merged, not either-or.** The reader's file is copied once and never
    rewritten, so a row this program ships later — every Mistral model, on
    2026-09-29 — would otherwise never reach an installation that already had
    a catalogue, and its runs would read "cost unknown" for ever. The reader's
    row still wins wherever both name a model: a corrected price is exactly
    what the copy exists to keep.

    A catalogue that will not parse is not fatal. It costs the reader their
    own rows, never their run — so a broken edit degrades to the shipped
    prices, and an unlisted model to "cost unknown".
    """
    out: dict[str, dict] = {}
    for path in [default_path()] + ([catalogue_path(home)] if home else []):
        for provider, models in _read(path).items():
            if provider == TOOLS or not isinstance(models, dict):
                continue
            for model_id, row in models.items():
                if isinstance(row, dict):
                    out[str(model_id)] = {**row, "provider": str(provider)}
    return out


def tool_price(provider: str, tool: str, home: Path | None = None) -> float | None:
    """What one call of a provider's tool costs, or `None` where nobody knows.

    Mistral's web search is billed per call on top of the tokens it adds, and
    on a quick look it is most of the bill (four calls, $0.12, against well
    under a cent of tokens). A meter that priced only tokens would call that
    run free.
    """
    for path in ([catalogue_path(home)] if home else []) + [default_path()]:
        row = ((_read(path).get(TOOLS) or {}).get(provider) or {}).get(tool)
        if isinstance(row, dict):
            try:
                return float(row["usd_per_call"])
            except (KeyError, TypeError, ValueError):
                continue
    return None


def price(model: str, tokens_in: int, tokens_out: int,
          home: Path | None = None) -> float | None:
    """What those tokens cost, or `None` where nobody knows.

    `None` rather than 0.0, and the difference is the whole contract: a run
    whose price is unknown must not be reported as free. `app/costs.py` makes
    the same distinction for the same reason.
    """
    row = load(home).get(model)
    if not row:
        return None
    try:
        return (tokens_in / 1e6) * float(row["usd_in"]) + (
            tokens_out / 1e6) * float(row["usd_out"])
    except (KeyError, TypeError, ValueError):
        return None


#: Who serves a model the catalogue has no row for, by its name alone. A
#: closed vocabulary of vendor prefixes, not a model list: a model released
#: tomorrow routes correctly the day it exists. Anything else is sent to the
#: OpenAI-shaped adapter, the format every gateway speaks.
_PREFIXES = (("claude-", "anthropic"), ("mistral-", "mistral"), ("magistral-", "mistral"))

#: The providers with a completion adapter (`app/providers/__init__.py`).
ADAPTERS = ("openai", "anthropic", "mistral")


def provider_for(model: str, home: Path | None = None) -> str:
    row = load(home).get(model) or {}
    if row.get("provider"):
        return str(row["provider"])
    return next((who for prefix, who in _PREFIXES if model.startswith(prefix)), "openai")


def _usable(provider: str, ready: set[str]) -> str:
    """"" when it can be used, or the reason it cannot — never silence."""
    if provider not in ADAPTERS:
        return f"no completion adapter for {provider}"
    if provider in ready:
        return ""
    return f"no {provider} key — add one on Settings"


def offered(home: Path | None = None, *, ready: set[str] | None = None,
            discovered: dict[str, list[str]] | None = None) -> list[dict]:
    """Every model this installation could be asked to use, best-described first.

    `ready` is the providers with a key (`app/keys.py`), `discovered` is what
    each endpoint listed. Both are passed in rather than fetched here: this
    module must be answerable with no network and no database, because it is
    read while rendering a settings page and a screen that blocks on a provider
    call is a screen that hangs when the provider is down.
    """
    ready = ready or set()
    rows = load(home)
    out = []
    for model_id, row in rows.items():
        provider = row.get("provider", "")
        out.append({
            "id": model_id,
            "label": str(row.get("label") or model_id),
            "provider": provider,
            "context": row.get("context"),
            "usd_in": row.get("usd_in"),
            "usd_out": row.get("usd_out"),
            "speed": str(row.get("speed") or ""),
            "unusable": _usable(provider, ready),
            "known": True,
        })

    # Anything an endpoint offers that the catalogue has never heard of. It is
    # selectable — a model released this morning should not wait for a release
    # of ours — and it is honest about what is missing: no price, no window,
    # and the reader can add a row if they want those.
    known = set(rows)
    for provider, ids in (discovered or {}).items():
        for model_id in ids:
            if model_id in known:
                continue
            out.append({
                "id": model_id,
                "label": model_id,
                "provider": provider,
                "context": None, "usd_in": None, "usd_out": None, "speed": "",
                "unusable": _usable(provider, ready),
                "known": False,
                "note": "not in your catalogue — usable, but its cost cannot "
                        "be reported until you add a row",
            })
    # Usable first, then cheapest, then by name. A reader scanning this is
    # deciding what to spend, so the column they are deciding on leads.
    out.sort(key=lambda one: (
        bool(one["unusable"]),
        one["usd_out"] if isinstance(one["usd_out"], (int, float)) else 1e9,
        one["id"],
    ))
    return out
