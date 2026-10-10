"""Mistral: one request that searches, reads and answers (B153).

The harness plane runs a coding-agent CLI to do a reading task, and on
2026-09-29 the reader reported what that costs: "Agent operations are slow and
not working properly". Measured the same day, the CLIs failed for reasons that
belong to the CLIs rather than to any run — fetches refused with 403, an agent
reading "you have no Kriko tools" as "you have no tools" and doing no research,
OAuth and quota walls, a Windows shim that mangles argv, ~104k tokens and ~30 s
per subject before a single page was read. None of those has a fix on our side
of the process boundary.

Mistral's Conversations API carries the one tool the task needs. A single POST
with `tools: [{"type": "web_search"}]` searches, opens pages when it wants to,
and answers — 9 s for a quick look on `mistral-small-latest`, measured. And
unlike a CLI's transcript, the response *returns what the search returned*:
each `tool.execution` entry holds the result urls and their text. That is what
makes grounding honest here: a quote is checked against the text the search
actually produced for that url, not against a paragraph the model says it read.

One more socket lives here for the paid plane (`ApiResearcher`): `completer`,
which is `llm.completer` pointed at Mistral's OpenAI-shaped endpoint. Not a
search socket: a forced one-search conversation per query would bill a model
call on top of every $0.03 search, and the paid plane's Exa and Tavily already
do that job for less.

**No accounting here**, as for the other adapters: `Reply` carries the counts
and the caller prices them, because two running totals are two answers to "how
much did this cost".
"""

import html
import json
import os
import re
from dataclasses import dataclass, field

from app.keys import require
from app.providers._http import post_json_or_why

DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
#: Fastest of the two measured on the quick-look brief (8.8 s against 46 s
#: for `mistral-large-latest`, which also opened five pages and so billed nine
#: tool calls to small's four). The reader can pick another in the agent row.
DEFAULT_MODEL = "mistral-small-latest"
#: A quick look answers in under ten seconds; research asks for more reading.
#: Two minutes is room for both and still ends a run whose connection hung.
TIMEOUT_SECONDS = 120.0
#: Where each result's text stops. The search's own snippets are a few
#: hundred characters; an opened page is the whole page, and grounding needs
#: the sentence rather than the site navigation around it — but never more
#: than a page's worth per url, or one forum thread becomes the run's memory.
MAX_SOURCE_CHARS = 60000

_TAG = re.compile(r"<[^>]+>")


def base_url() -> str:
    return (os.environ.get("MISTRAL_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


@dataclass
class Reply:
    """What one conversation produced, and what it cost to produce it."""

    text: str = ""
    #: url -> {"title", "text"}: every result the search tool returned in this
    #: call, with the text it returned for it. The grounding source.
    sources: dict[str, dict] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    #: `None` when the response had no usage block — "cannot count", never 0.
    tokens_in: int | None = None
    tokens_out: int | None = None
    #: Billed tool calls (searches and page opens alike), from `usage`.
    tool_calls: int = 0
    #: Why there is no answer, in words a reader can act on. `""` on success.
    error: str = ""


def _plain(text) -> str:
    """Search text without the markup the search engine wraps it in."""
    return _TAG.sub("", html.unescape(str(text or ""))).strip()


def _add_source(sources: dict, url, title, text: str) -> None:
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return
    row = sources.setdefault(url, {"title": "", "text": ""})
    row["title"] = row["title"] or _plain(title)
    text = _plain(text)
    if text and text not in row["text"]:
        row["text"] = (row["text"] + "\n\n" + text).strip()[:MAX_SOURCE_CHARS]


def _results(raw) -> list[dict]:
    """The result rows of one `web_search` execution, in either shape.

    Measured 2026-09-29, the tool answers two ways: a *search* returns a JSON
    object of numbered results, each with `url`, `title`, `description` and
    `snippets`; an *opened page* returns a list of `{"type": "text", "text":
    "<json>"}` chunks whose JSON carries `url`, `title` and the page's
    `content`. The first parser written against it knew only the first shape
    and crashed on the second.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    rows: list[dict] = []
    if isinstance(raw, dict):
        rows = [one for one in raw.values() if isinstance(one, dict)]
    elif isinstance(raw, list):
        for chunk in raw:
            if not isinstance(chunk, dict):
                continue
            if isinstance(chunk.get("text"), str) and "url" not in chunk:
                try:
                    inner = json.loads(chunk["text"])
                except ValueError:
                    continue
                if isinstance(inner, dict):
                    rows.append(inner)
            else:
                rows.append(chunk)
    return rows


def parse(body: dict) -> Reply:
    """A Conversations API response, as a `Reply`. Pure — tested on fixtures."""
    reply = Reply()
    texts: list[str] = []
    for entry in (body or {}).get("outputs") or ():
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == "tool.execution":
            try:
                arguments = json.loads(entry.get("arguments") or "{}")
            except (TypeError, ValueError):
                arguments = {}
            query = arguments.get("query") if isinstance(arguments, dict) else None
            if isinstance(query, str) and query.strip():
                reply.queries.append(query.strip())
            info = entry.get("info")
            for row in _results(info.get("result") if isinstance(info, dict) else None):
                parts = [row.get("description"), row.get("content")]
                parts += list(row.get("snippets") or ())
                _add_source(reply.sources, row.get("url"), row.get("title"),
                            "\n".join(str(one) for one in parts if one))
        elif kind == "message.output":
            content = entry.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(
                    str(chunk.get("text") or "")
                    for chunk in content
                    if isinstance(chunk, dict) and chunk.get("type") == "text"
                )
    reply.text = "".join(texts).strip()
    usage = (body or {}).get("usage")
    if isinstance(usage, dict):
        prompt = _count(usage.get("prompt_tokens"))
        # The search results the tool put in front of the model are input the
        # model read, and billed as such; counting only `prompt_tokens` would
        # report a 25k-token call as a 1k one.
        connector = _count(usage.get("connector_tokens"))
        if prompt is not None or connector is not None:
            reply.tokens_in = (prompt or 0) + (connector or 0)
        reply.tokens_out = _count(usage.get("completion_tokens"))
        connectors = usage.get("connectors")
        if isinstance(connectors, dict):
            reply.tool_calls = sum(
                one for one in map(_count, connectors.values()) if one is not None
            )
    return reply


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def converse(prompt: str, *, model: str = "", api_key: str = "",
             timeout: float = TIMEOUT_SECONDS, search: bool = True,
             max_tokens: int = 0) -> Reply:
    """One conversation turn: the prompt in, the answer and its sources out.

    `store: false` because nothing here continues a conversation, and a
    stored one is a copy of the reader's research on a server they did not
    choose to keep it on. No `agent_id`: the tool list travels with the
    request, which is what lets one key serve every operation without the
    reader creating an agent on Mistral's console first.
    """
    completion_args: dict = {"temperature": 0.0}
    if max_tokens:
        completion_args["max_tokens"] = int(max_tokens)
    payload: dict = {
        "model": model or DEFAULT_MODEL,
        "inputs": prompt,
        "store": False,
        # A transcription task with a JSON contract: the quote must come back
        # byte-identical or the grounding check refuses it.
        "completion_args": completion_args,
    }
    if search:
        payload["tools"] = [{"type": "web_search"}]
    body, why = post_json_or_why(
        f"{base_url()}/conversations",
        payload,
        {"authorization": f"Bearer {api_key or require('mistral')}"},
        timeout=timeout,
    )
    if why:
        return Reply(error=why)
    reply = parse(body)
    if not reply.text:
        reply.error = "Mistral answered with no text"
    return reply


def completer(model: str = "", max_tokens: int | None = None):
    """`complete(prompt)` for the paid plane, on Mistral's chat endpoint.

    The endpoint speaks the OpenAI wire format, so this is the existing
    adapter pointed elsewhere rather than a second implementation of it.
    """
    from app.providers import llm

    return llm.completer(api_key=require("mistral"), base_url=base_url(),
                         model=model or DEFAULT_MODEL, max_tokens=max_tokens)
