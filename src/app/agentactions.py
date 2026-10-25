"""Small, named changes Kriko Agent may make in the app on the reader's behalf.

Three rules keep this from becoming a second, unbounded agent:

* **A closed vocabulary.** Every action is a row in `ACTIONS`; there is no
  free-form command and no path from a web page's words to a new action.
* **Low-risk actions run; spending and installing are proposals.** `remember`
  and `open` change only what the reader asked for and can be undone on the
  screen they name. Anything that spends credits or changes installed catalogs
  comes back as a `proposed` action for a press, never as work the model did.
* **The action is data, not prose.** The reply carries the same object the
  screen draws, so "I saved it" is only said when a row was written.

The vocabulary is deliberately small. It grows when a screen can show the
result and a test can prove the change; an action with no visible undo is not
low-risk, however small it looks.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app import buyer
from app.web import state

#: The screens `open` may name. A short list on purpose: each is a place the
#: desktop and the phone both have, so one action reads the same on either.
SCREENS = {
    "chat": "Chat",
    "catalogs": "Catalogs",
    "compare": "Compare",
    "queue": "Queue",
    "history": "History",
    "for-you": "For you",
    "settings": "Settings",
    "logs": "Logs",
}

#: Which part of the reader's profile `remember` may write. These are the
#: profile's own lists (`buyer.clean`), so nothing new is stored for the agent.
PROFILE_LISTS = {
    "must": "Must have",
    "avoid": "Avoid",
    "prefer": "Would like",
    "distrust": "Do not trust",
    "about": "About you",
}

MAX_FACT_CHARS = 160
MAX_ABOUT_CHARS = 1200


def _action(kind: str, *, status: str, title: str, detail: str,
            params: dict | None = None) -> dict:
    return {
        "id": f"{kind}-{secrets.token_hex(4)}",
        "kind": kind,
        "status": status,
        "title": title,
        "detail": detail,
        "params": params or {},
    }


def _words(value, limit: int = MAX_FACT_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


def remember(conn, *, fact: str, list_name: str = "prefer") -> dict:
    """Add one durable statement to the reader's profile, without duplicates."""
    list_name = str(list_name or "").strip().casefold()
    if list_name not in PROFILE_LISTS:
        return {"status": "failed",
                "note": f"remember has no list called {list_name!r}"}
    fact = _words(fact)
    if not fact:
        return {"status": "failed", "note": "remember needs a fact"}

    profile = buyer.read(conn)
    if list_name == "about":
        current = str(profile.get("about") or "").strip()
        if fact.casefold() in current.casefold():
            action = _action("remember", status="done", title="Already known",
                             detail=fact, params={"list": list_name, "fact": fact})
            return {"status": "done", "action": action, "note": "It was already saved."}
        joined = f"{current} {fact}".strip()
        if len(joined) > MAX_ABOUT_CHARS:
            return {"status": "failed",
                    "note": "The About note is full; the reader can shorten it in For you."}
        profile["about"] = joined
    else:
        items = list(profile.get(list_name) or [])
        if fact.casefold() in {one.casefold() for one in items}:
            action = _action("remember", status="done", title="Already known",
                             detail=fact, params={"list": list_name, "fact": fact})
            return {"status": "done", "action": action, "note": "It was already saved."}
        if len(items) >= buyer.MAX_ITEMS:
            return {"status": "failed",
                    "note": f"{PROFILE_LISTS[list_name]} already holds "
                            f"{buyer.MAX_ITEMS} items; the reader can edit it in For you."}
        items.append(fact)
        profile[list_name] = items
    buyer.save(conn, profile)
    action = _action(
        "remember", status="done",
        title=f"Saved to {PROFILE_LISTS[list_name]}",
        detail=fact, params={"list": list_name, "fact": fact},
    )
    return {"status": "done", "action": action,
            "note": f"Saved to {PROFILE_LISTS[list_name]} in For you."}


def open_screen(*, screen: str, item: str = "") -> dict:
    """A navigation the screen performs. Nothing is written here, and the
    action waits for the reader's press: leaving an answer is their move."""
    screen = str(screen or "").strip().casefold()
    if screen not in SCREENS:
        return {"status": "failed", "note": f"there is no screen called {screen!r}"}
    action = _action(
        "open", status="proposed", title=f"Open {SCREENS[screen]}",
        detail=item[:120], params={"screen": screen, "item": item[:200]},
    )
    return {"status": "proposed", "action": action,
            "note": "The screen shows an Open button; the reader presses it."}


def _public_url(raw: object) -> str:
    parts = urlsplit(str(raw or "").strip())
    if (parts.scheme.lower() not in ("http", "https") or not parts.hostname
            or parts.username or parts.password):
        return ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path or "/", parts.query, ""))


def start_quick_look(*, product: str, page_url: str = "") -> dict:
    """Propose the paid Quick Look. The screen starts it on a press.

    A Quick Look spends the reader's credits (or a shared allowance), so it is
    never something a web page's text can trigger. The URL is accepted only
    when it is a public HTTP(S) address and is kept as the listing the look is
    about; the product name is what the research actually reads.
    """
    product = _words(product, 200)
    if not product:
        return {"status": "failed", "note": "a Quick Look needs the product's name"}
    raw_url = str(page_url or "").strip()
    url = _public_url(raw_url) if raw_url else ""
    if raw_url and not url:
        return {"status": "failed", "note": "the listing URL must be a public http or https address"}
    detail = f"{product} · {urlsplit(url).hostname}" if url else product
    action = _action(
        "start_quick_look", status="proposed", title="Start a Quick Look",
        detail=detail, params={"product": product, "page_url": url},
    )
    return {"status": "proposed", "action": action,
            "note": "The screen shows a Start button; the reader presses it."}


def describe() -> list[dict]:
    """The tools the model is offered, in the OpenAI function-call shape.

    `remember` is the low-risk change; `open` is navigation and waits for a
    press; `start_quick_look` is the paid action and is only ever proposed.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": (
                    "Save one lasting fact about the reader to their Kriko profile "
                    "(For you): a hard requirement, something to avoid, a "
                    "preference, a brand they distrust, or a sentence about how "
                    "they use things. Use it only when the reader states a lasting "
                    "need (\"I need it quiet\", \"never a Samsung\"), never for a "
                    "one-off detail of this question. It is saved immediately and "
                    "the reader can edit it in For you."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "minLength": 1, "maxLength": MAX_FACT_CHARS},
                        "list": {"type": "string", "enum": list(PROFILE_LISTS),
                                 "description": "Where it belongs. Default would like."},
                    },
                    "required": ["fact"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "open",
                "description": (
                    "Take the reader to a screen in Kriko when they asked to see "
                    "it (\"show me my catalogs\", \"open my history\"). Never use it "
                    "to end an answer or to escape a question you cannot answer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "screen": {"type": "string", "enum": list(SCREENS)},
                        "item": {"type": "string", "maxLength": 200},
                    },
                    "required": ["screen"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_quick_look",
                "description": (
                    "Offer to run a Quick Look on one product now. It spends the "
                    "reader's credits, so it is only proposed; the screen shows a "
                    "Start button and nothing runs until it is pressed. Use it when "
                    "the reader asked to check or research a specific product, and "
                    "include a listing URL only when one of the results is that "
                    "product's own page."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string", "minLength": 1, "maxLength": 200},
                        "page_url": {"type": "string", "maxLength": 2048},
                    },
                    "required": ["product"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def execute(name: str, arguments: dict, *, app_state_path: Path | str) -> dict:
    """Run one low-risk action and return `{status, action, note}`.

    A failure is data for the model, never an exception that ends the turn: an
    action that could not be done must be sayable in the answer.
    """
    name = str(name or "").strip()
    arguments = arguments if isinstance(arguments, dict) else {}
    if name == "open":
        return open_screen(screen=str(arguments.get("screen") or ""),
                           item=str(arguments.get("item") or ""))
    if name == "start_quick_look":
        return start_quick_look(product=str(arguments.get("product") or ""),
                                page_url=str(arguments.get("page_url") or ""))
    if name == "remember":
        try:
            conn = state.connect(Path(app_state_path))
        except Exception as error:  # noqa: BLE001 — the model gets the reason
            return {"status": "failed", "note": f"the profile is not readable: {type(error).__name__}"}
        try:
            return remember(conn, fact=str(arguments.get("fact") or ""),
                            list_name=str(arguments.get("list") or "prefer"))
        finally:
            conn.close()
    return {"status": "failed", "note": f"there is no app action called {name!r}"}


def tool_names() -> set[str]:
    """The function names the adapter may dispatch to this module."""
    return {tool["function"]["name"] for tool in describe()}


def as_message(result: dict) -> str:
    """The tool result the model reads: small, JSON, and never a secret."""
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
