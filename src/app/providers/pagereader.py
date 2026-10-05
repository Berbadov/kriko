"""Reading a page through a hosted reader, the rung after the plain fetch.

A site that refuses this app's own fetcher (Cloudflare's AI-bot rules answer
`Kriko/1.0` with a 403, exactly as they answer Claude Code's `Claude-User`)
is not unreadable, it is unreadable *from here*. A hosted reader fetches it
from the reader service's own infrastructure instead, which those rules do
not name. The harness plane already attaches Exa's hosted MCP as a per-run
page reader (B155); this module is the same door opened directly, for the
planes that read pages in this process: `fetch.py`'s ladder, with no MCP
client, no per-run config and no session wait.

The wire is JSON-RPC over plain HTTP, exactly as `exa_mcp.py` already speaks
it for search: `initialize` opens a session, `tools/call` asks, and the
reply is one JSON message, possibly dressed as a server-sent event.

Two hosted readers, tried in order: Exa's, then Parallel's
(`https://search.parallel.ai/mcp`, tool `web_fetch`, also keyless). A
courtesy is not a contract, and one vendor's courtesy is a single point of
failure, so the second reader exists to make the first replaceable. Every
failure is `""`, so the ladder can simply fall through and report the page
unread rather than half-read.
"""

import json
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

EXA_ENDPOINT = "https://mcp.exa.ai/mcp"
EXA_TOOL = "web_fetch_exa"
PARALLEL_ENDPOINT = "https://search.parallel.ai/mcp"
PARALLEL_TOOL = "web_fetch"
PROTOCOL = "2025-06-18"

#: Kept for the harness plane's per-run config, which names one door.
ENDPOINT = EXA_ENDPOINT
TOOL = EXA_TOOL

#: `extract` truncates to 12 000 characters, so more than this is paying a
#: courtesy for text the run will never read.
MAX_CHARACTERS = 20_000
TIMEOUT = 45.0


def user_agent() -> str:
    from app.version import app_version

    return f"kriko/{app_version()} (+https://github.com/Berbadov/kriko)"


def _rpc(endpoint: str, body: dict, session: str = "") -> tuple[dict, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": user_agent(),
    }
    if session:
        headers["mcp-session-id"] = session
    request = urllib.request.Request(
        endpoint, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            session = response.headers.get("mcp-session-id") or session
            raw = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return {}, ""
    for line in raw.splitlines():
        line = line[6:] if line.startswith("data: ") else line
        if line.startswith("{"):
            try:
                return json.loads(line), session
            except ValueError:
                break
    return {}, ""


_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_BARE_DATA = re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+")


def plain(text: str) -> str:
    """Markdown's addresses out, its words kept.

    A reader service answers in markdown, where every link carries its url
    and every image its address: tokens the model pays for and can never
    quote from. `[the text](url)` becomes `the text` and an image becomes
    its alt text, so what is left is what the page says. Then the same line
    filter the plain fetch uses drops the menus.
    """
    from app.providers.fetch import prose_lines  # noqa: PLC0415 — fetch imports this module

    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _BARE_DATA.sub("", text)
    lines = prose_lines(line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse(text: str, url: str) -> str:
    """The one page's prose out of Exa's answer, or "".

    Exa answers one text per URL, each opened by a `URL:` line and preceded
    by a heading. For a single URL the whole answer is that page, minus the
    header lines the reader service adds and the page does not.
    """
    lines: list[str] = text.splitlines()
    kept: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("URL:"):
            inside = line[4:].strip() == url
            continue
        if line.startswith("# ") and not kept:
            continue
        if inside:
            kept.append(line)
    body = "\n".join(kept).strip()
    if not body:
        return text.strip() if "URL:" not in text else ""
    return body


def parse_parallel(text: str, url: str) -> str:
    """The one page's prose out of Parallel's answer, or "".

    Parallel answers JSON inside the text: one `results` list, each entry a
    page with `excerpts`. The asked page is the entry whose `url` matches;
    its excerpts are its prose.
    """
    try:
        payload = json.loads(text)
    except ValueError:
        return ""
    for entry in payload.get("results") or []:
        if entry.get("url") == url:
            return "\n".join(
                str(part)
                for part in entry.get("excerpts") or []
                if isinstance(part, str)
            )
    return ""


def _asked(target: str, tool: str, url: str) -> str:
    """One reader's raw text answer, "" on any failure."""
    reply, session = _rpc(
        target,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "kriko", "version": "0"},
            },
        },
    )
    if not session:
        return ""
    reply, _ = _rpc(
        target,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": {"urls": [url], "maxCharacters": MAX_CHARACTERS},
            },
        },
        session,
    )
    result = reply.get("result") or {}
    if reply.get("error") or result.get("isError"):
        return ""
    return "\n".join(
        str(part.get("text", ""))
        for part in result.get("content") or []
        if isinstance(part, dict) and part.get("type") == "text"
    )


def read(url: str, endpoint: str = "") -> str:
    """The page's text through the hosted readers, "" when none read it.

    Exa first, Parallel second: one initialize and one call per page per
    reader, so a kept session would be state whose lifetime nobody owns.
    "" on every failure, so the ladder in `fetch.py` can simply fall
    through and report the page unread rather than half-read.
    """
    if not url.lower().startswith(("http://", "https://")):
        return ""
    if urlsplit(url).netloc == urlsplit(EXA_ENDPOINT).netloc:
        return ""
    if endpoint:
        return plain(parse(_asked(endpoint, EXA_TOOL, url), url))[:MAX_CHARACTERS]
    for target, tool, lift in (
        (EXA_ENDPOINT, EXA_TOOL, parse),
        (PARALLEL_ENDPOINT, PARALLEL_TOOL, parse_parallel),
    ):
        page = plain(lift(_asked(target, tool, url), url))
        if page:
            return page[:MAX_CHARACTERS]
    return ""
