"""Search through Exa's free hosted MCP endpoint, no key (B171, decision D3).

The local plane prefers a search service on this machine (OpenSERP). When
none answers, this is the fallback, so a local model alone is enough to run:
`https://mcp.exa.ai/mcp` serves the `web_search_exa` tool over streamable HTTP
to anyone, without an account.

It is a different door from `exa.py`, which is the paid plane's keyed REST
API. The wire here is JSON-RPC: `initialize` opens a session, `tools/call`
asks, and the reply is one server-sent event carrying a JSON message. The text
of a result set is a run of entries that each begin `Title:` and `URL:`; the
pages themselves are read by the stock reader, not taken from this answer.

The client names itself honestly (`kriko/<version>`): a free endpoint is a
courtesy, and a service that would rather not be used by an app is entitled to
say so. A failure raises `LocalSearchError`, which the plane reports in the
job log and its politeness scheduler treats as a reason to rotate.
"""

import json
import urllib.error
import urllib.request

from kriko.research.politeness import LocalSearchError

ENDPOINT = "https://mcp.exa.ai/mcp"
PROTOCOL = "2025-06-18"
TOOL = "web_search_exa"
TIMEOUT = 60.0


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
        endpoint, data=json.dumps(body).encode("utf-8"), headers=headers,
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            session = response.headers.get("mcp-session-id") or session
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise LocalSearchError(f"{endpoint} answered HTTP {error.code}") from error
    except (urllib.error.URLError, OSError) as error:
        raise LocalSearchError(f"{endpoint} is not reachable") from error
    for line in raw.splitlines():
        line = line[6:] if line.startswith("data: ") else line
        if line.startswith("{"):
            try:
                return json.loads(line), session
            except ValueError:
                break
    return {}, session


def parse(text: str) -> list[dict]:
    """`[{"url", "title", "site"}]` from the tool's text.

    Entries are runs of lines; `Title:` opens one and the first `URL:` after
    it closes the pair. Anything else in the text (dates, highlights) is the
    page's own words and is left for the reader to fetch.
    """
    from urllib.parse import urlsplit

    out, title = [], ""
    for line in text.splitlines():
        if line.startswith("Title:"):
            title = line[6:].strip()
        elif line.startswith("URL:"):
            url = line[4:].strip()
            if url.startswith(("http://", "https://")):
                out.append({"url": url, "title": title,
                            "site": urlsplit(url).netloc})
            title = ""
    return out


def searcher(endpoint: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`, like every searcher.

    The session opens on the first query and is kept for the run's others.
    """
    target = endpoint or ENDPOINT
    state = {"session": ""}

    def search(query: str, limit: int = 5) -> list[dict]:
        if not state["session"]:
            _, state["session"] = _rpc(target, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                           "clientInfo": {"name": "kriko", "version": "0"}}})
        reply, _ = _rpc(target, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": TOOL, "arguments": {
                "query": query, "numResults": max(1, int(limit))}}},
            state["session"])
        if reply.get("error"):
            state["session"] = ""  # a stale session is reopened next time
            raise LocalSearchError(
                f"{target} refused the search: {reply['error']}")
        result = reply.get("result") or {}
        text = "\n".join(
            str(part.get("text", "")) for part in result.get("content") or []
            if isinstance(part, dict) and part.get("type") == "text")
        if result.get("isError"):
            raise LocalSearchError(f"{target} reported a failed search")
        return parse(text)[: max(1, int(limit))]

    return search


#: The second door for `search_with_fallback` below. Parallel's hosted MCP
#: serves `web_search` keyless, on the same wire, so a courtesy that stops
#: answering stops the plane rather than the research.
PARALLEL_ENDPOINT = "https://search.parallel.ai/mcp"
PARALLEL_TOOL = "web_search"


def parse_parallel(text: str, limit: int) -> list[dict]:
    """`[{"url", "title", "site"}]` from Parallel's JSON-in-text answer."""
    from urllib.parse import urlsplit
    try:
        payload = json.loads(text)
    except ValueError:
        return []
    out = []
    for entry in payload.get("results") or []:
        url = str(entry.get("url") or "")
        if url.startswith(("http://", "https://")):
            out.append({"url": url, "title": str(entry.get("title") or ""),
                        "site": urlsplit(url).netloc})
    return out[: max(1, int(limit))]


def parallel_searcher(endpoint: str = ""):
    """`search(query, limit) -> [{"url", "title", "site"}]`, like every searcher.

    Parallel's tool asks for an `objective` rather than a bare query, and the
    query itself is a fair objective, so it is passed through unchanged.
    """
    target = endpoint or PARALLEL_ENDPOINT
    state = {"session": ""}

    def search(query: str, limit: int = 5) -> list[dict]:
        if not state["session"]:
            _, state["session"] = _rpc(target, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                           "clientInfo": {"name": "kriko", "version": "0"}}})
        reply, _ = _rpc(target, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": PARALLEL_TOOL, "arguments": {
                "objective": query, "search_queries": [query]}}},
            state["session"])
        result = reply.get("result") or {}
        if reply.get("error") or result.get("isError"):
            state["session"] = ""
            raise LocalSearchError(f"{target} refused the search")
        text = "\n".join(
            str(part.get("text", "")) for part in result.get("content") or []
            if isinstance(part, dict) and part.get("type") == "text")
        return parse_parallel(text, limit)

    return search


def search_with_fallback():
    """Exa's searcher, and Parallel's behind it for the failures.

    A refusal from the first door is a rotation, not an error: the plane's
    scheduler treats `LocalSearchError` as a reason to rotate and this is
    the rotation. Both doors are courtesies, so neither is allowed to be
    the single one; the second is a name and a tool away from a third.
    """
    first = searcher()
    second = parallel_searcher()

    def search(query: str, limit: int = 5) -> list[dict]:
        try:
            found = first(query, limit)
        except LocalSearchError:
            return second(query, limit)
        if found:
            return found
        return second(query, limit)

    return search
