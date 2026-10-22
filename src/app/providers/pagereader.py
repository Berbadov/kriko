"""Reading a page through Parallel's hosted reader after the plain fetch.

A site that refuses this app's own fetcher (Cloudflare's AI-bot rules answer
`Kriko/1.0` with a 403, exactly as they answer Claude Code's `Claude-User`)
is not unreadable, it is unreadable *from here*. A hosted reader fetches it
from the reader service's own infrastructure instead, which those rules do
not name. This module reads pages for the planes that run in this process:
`fetch.py`'s ladder, with no MCP client, no per-run config and no session wait.

The wire is JSON-RPC over plain HTTP: `initialize` opens a session,
`tools/call` asks, and the reply is one JSON message, possibly dressed as a
server-sent event.

One hosted reader: Parallel (`https://search.parallel.ai/mcp`, tool
`web_fetch`). Every failure is `""`, so the ladder can fall through and
report the page unread rather than half-read.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from app.providers import egress, network
from app.providers._http import _read_body
from urllib.parse import urlsplit

from app.providers.fetch import LINK_CLOSE, LINK_OPEN, prose_lines

log = logging.getLogger(__name__)

PARALLEL_ENDPOINT = "https://search.parallel.ai/mcp"
PARALLEL_TOOL = "web_fetch"
PROTOCOL = "2025-06-18"

ENDPOINT = PARALLEL_ENDPOINT
TOOL = PARALLEL_TOOL

#: `extract` truncates to 12 000 characters, so more than this is paying a
#: courtesy for text the run will never read.
MAX_CHARACTERS = 20_000
TIMEOUT = 45.0


def user_agent() -> str:
    from app.version import app_version

    return f"kriko/{app_version()} (+https://github.com/Berbadov/kriko)"


def _rpc(endpoint: str, body: dict, session: str = "", *,
         timeout: float = TIMEOUT, check_cancelled=None) -> tuple[dict, str]:
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
        if check_cancelled is not None:
            check_cancelled()
        options = {"check": check_cancelled} if check_cancelled is not None else {}
        with network.urlopen(request, timeout=timeout, **options) as response:
            session = response.headers.get("mcp-session-id") or session
            # The whole body inside `timeout`, not just each wait on the
            # socket: a reader service that drips a byte at a time never trips
            # a per-recv timeout (`_http._read_body`).
            got, why = _read_body(response, timeout)
            if why:
                log.info("the page reader service %s", why)
                return {}, session
            raw = got.decode("utf-8", "replace")
        if check_cancelled is not None:
            check_cancelled()
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


#: UTF-8 read as Windows-1252 leaves these marks: `â€"` for a dash or quote,
#: `Ã©` for an accented letter. A reader service that does it hands the model
#: (and the reader's screen, in every quote) `trigger—it` as `triggerâ€”it`.
_MOJIBAKE = re.compile("[ÂÃâ][\u0080-¿ŒœŠšŸŽžƒˆ˜–-›€™]")


def _unmangle_line(line: str) -> str:
    if not _MOJIBAKE.search(line):
        return line
    raw = bytearray()
    for char in line:
        try:
            raw += char.encode("cp1252")
        except UnicodeEncodeError:
            if ord(char) > 255:
                return line
            raw.append(ord(char))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return line


def unmangle(text: str) -> str:
    """Undo UTF-8 that a service decoded as Windows-1252, line by line.

    A line is only changed when it shows the telltale pairs *and* the repaired
    bytes are valid UTF-8, so a page that really says `Ã©` in one line is left
    as it is and never costs the lines around it.
    """
    return "\n".join(_unmangle_line(line) for line in text.split("\n"))


def plain(text: str) -> str:
    """Markdown's addresses out, its words kept.

    A reader service answers in markdown, where every link carries its url
    and every image its address: tokens the model pays for and can never
    quote from. `[the text](url)` becomes `the text` and an image becomes
    its alt text, so what is left is what the page says. Then the same line
    filter the plain fetch uses drops the menus (a run of lines that are
    each one link).
    """
    text = unmangle(text)
    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: LINK_OPEN + m.group(1) + LINK_CLOSE, text)
    text = _BARE_DATA.sub("", text)
    lines = prose_lines(line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


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


def _asked(target: str, tool: str, url: str, *, timeout: float = TIMEOUT,
           check_cancelled=None) -> str:
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
        }, timeout=timeout, check_cancelled=check_cancelled,
    )
    if not session:
        return ""
    if check_cancelled is not None:
        check_cancelled()
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
        session, timeout=timeout, check_cancelled=check_cancelled,
    )
    result = reply.get("result") or {}
    if reply.get("error") or result.get("isError"):
        return ""
    return "\n".join(
        str(part.get("text", ""))
        for part in result.get("content") or []
        if isinstance(part, dict) and part.get("type") == "text"
    )


def read(url: str, endpoint: str = "", *, timeout: float = TIMEOUT,
         check_cancelled=None, allow_private: bool = False) -> str:
    """The page's text through the hosted readers, "" when none read it.

    One initialize and one call per page, so a kept session would be state
    whose lifetime nobody owns.
    "" on every failure, so the ladder in `fetch.py` can simply fall
    through and report the page unread rather than half-read.
    """
    if not url.lower().startswith(("http://", "https://")):
        return ""
    if urlsplit(url).netloc == urlsplit(PARALLEL_ENDPOINT).netloc:
        return ""
    # The same egress rule the plain fetch applies. This rung exists to read a
    # page this machine could not; it must not become a way to read *this
    # machine* on a URL someone else supplied.
    if egress.reason_to_refuse(url, allow_private=allow_private):
        return ""
    if check_cancelled is not None:
        check_cancelled()
    if endpoint:
        target = endpoint
    else:
        target = PARALLEL_ENDPOINT
    page = plain(parse_parallel(_asked(target, PARALLEL_TOOL, url, timeout=timeout,
                                       check_cancelled=check_cancelled), url))
    return page[:MAX_CHARACTERS]
