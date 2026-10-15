"""One JSON request, with the failure modes named.

Every provider below needs the same four things: a timeout, a body decoded as
JSON, an error that does not take the whole run down, and no key anywhere in
what gets logged. Written once here so a provider is only its endpoint and its
response shape.
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from app.providers import network

log = logging.getLogger(__name__)

#: Long enough for a search or a completion, short enough that a hung provider
#: cannot make a job look stuck forever. A research run has many of these; a
#: 300-second default would let one dead host outlast the reader's patience.
TIMEOUT = 45.0


class StreamCancelled(Exception):
    """A local reader stopped consuming a provider's SSE response."""


def post_json(url: str, payload: dict, headers: dict, timeout: float = TIMEOUT) -> dict:
    """POST `payload`, return the decoded reply, or `{}` on any failure.

    `{}` rather than an exception because a provider that is briefly down must
    degrade a run, not fail it: `gather` skips a query that found nothing and
    `extract` returns no findings for a document it could not reason about,
    which are both already handled paths. The one thing that must not happen is
    the key reaching the log — so the error is reported by *type*, never by
    echoing the request.
    """
    return post_json_or_why(url, payload, headers, timeout)[0]


def post_json_or_why(url: str, payload: dict, headers: dict,
                     timeout: float = TIMEOUT) -> tuple[dict, str]:
    """`post_json`, plus the reason in the reader's terms when it failed.

    For a caller whose *whole run* is this one request (B153: the API agent),
    where `{}` alone would turn "your key was refused" and "the vendor is
    down" into the same silent empty answer. The reason names the status and
    what it usually means, and never the request — the body of an error may
    quote the key back.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with network.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace")) or {}, ""
    except urllib.error.HTTPError as error:
        # The status is diagnostic and safe; the body may quote the request.
        log.warning("%s answered HTTP %s", _host(url), error.code)
        return {}, f"{_host(url)} answered HTTP {error.code}{_MEANING.get(error.code, '')}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("%s unreachable: %s", _host(url), type(error).__name__)
        return {}, f"{_host(url)} unreachable ({type(error).__name__})"
    except (json.JSONDecodeError, ValueError):
        log.warning("%s answered something that is not JSON", _host(url))
        return {}, f"{_host(url)} answered something that is not JSON"


def post_sse_or_why(url: str, payload: dict, headers: dict, timeout: float,
                    on_event, *, cancel_event: threading.Event | None = None
                    ) -> tuple[int, str]:
    """POST JSON and deliver each SSE `data:` object as it is received.

    Provider error bodies are never returned or logged because they can echo
    credentials. Parsing and callback errors remain visible to the caller;
    only transport and HTTP failures become the same safe short reason as the
    buffered helper above.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "accept": "text/event-stream", **headers},
        method="POST",
    )
    count = 0
    data_lines: list[str] = []
    callback_error: BaseException | None = None

    def deliver() -> None:
        nonlocal count, callback_error
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        if raw == "[DONE]":
            return
        event = json.loads(raw)
        if isinstance(event, dict):
            try:
                on_event(event)
            except BaseException as error:
                # Callback failures (including cancellation) are part of the
                # caller's control flow, never a network or JSON diagnosis.
                callback_error = error
                raise
            count += 1

    try:
        with network.urlopen(request, timeout=timeout) as response:
            watcher_done = threading.Event()
            watcher = None
            if cancel_event is not None:
                def close_on_cancel() -> None:
                    while not watcher_done.wait(0.025):
                        if cancel_event.is_set():
                            response.close()
                            return

                watcher = threading.Thread(
                    target=close_on_cancel, name="kriko-sse-cancel", daemon=True,
                )
                watcher.start()
            try:
                for raw_line in response:
                    if cancel_event is not None and cancel_event.is_set():
                        raise StreamCancelled("provider stream canceled")
                    line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                    if not line:
                        deliver()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    # `event:`, `id:`, comments and retry hints do not carry
                    # the provider payload and can be ignored.
                if cancel_event is not None and cancel_event.is_set():
                    raise StreamCancelled("provider stream canceled")
                deliver()
            finally:
                watcher_done.set()
                if watcher is not None:
                    watcher.join(timeout=0.1)
        return count, ""
    except urllib.error.HTTPError as error:
        if callback_error is not None:
            raise callback_error
        log.warning("%s answered HTTP %s", _host(url), error.code)
        return count, f"{_host(url)} answered HTTP {error.code}{_MEANING.get(error.code, '')}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        if callback_error is not None:
            raise callback_error
        if cancel_event is not None and cancel_event.is_set():
            raise StreamCancelled("provider stream canceled") from error
        log.warning("%s unreachable: %s", _host(url), type(error).__name__)
        return count, f"{_host(url)} unreachable ({type(error).__name__})"
    except (json.JSONDecodeError, ValueError):
        if callback_error is not None:
            raise callback_error
        if cancel_event is not None and cancel_event.is_set():
            raise StreamCancelled("provider stream canceled")
        log.warning("%s answered something that is not an event stream", _host(url))
        return count, f"{_host(url)} answered something that is not an event stream"


#: What a status usually means for a keyed API, said once so every provider
#: that reports one says the same thing.
_MEANING = {
    400: " (the request was refused as malformed)",
    401: " (the key was refused — replace it in Settings → Research)",
    402: " (the account is out of credit)",
    403: " (the key may not use this — check the plan it is on)",
    429: " (rate limit or quota reached — wait, or check the plan)",
    500: " (the vendor failed — try again)",
    502: " (the vendor failed — try again)",
    503: " (the vendor is overloaded — try again)",
}


def _host(url: str) -> str:
    """The hostname, for a log line that names no path and no query."""
    from urllib.parse import urlsplit

    return urlsplit(url).netloc or url
