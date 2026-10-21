"""One JSON request, with the failure modes named.

Every provider below needs the same four things: a timeout, a body decoded as
JSON, an error that does not take the whole run down, and no key anywhere in
what gets logged. Written once here so a provider is only its endpoint and its
response shape.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from app.providers import network

log = logging.getLogger(__name__)

#: Long enough for a search or a completion, short enough that a hung provider
#: cannot make a job look stuck forever. A research run has many of these; a
#: 300-second default would let one dead host outlast the reader's patience.
TIMEOUT = 45.0

#: Statuses worth a second attempt: the vendor is busy, not wrong. A 4xx that is
#: not 429 is the request's fault and repeating it only spends the reader's
#: money twice.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: One attempt plus two retries. `_MEANING` below tells the reader to "try
#: again" for exactly these statuses, and until this existed nothing did: one
#: 503 removed a document from a paid run and the reason was a log line.
RETRY_ATTEMPTS = 3

#: Seconds before the first retry, doubled each time. A Retry-After header wins
#: when the vendor sends one, capped so a hostile or confused value cannot hold
#: a job open.
RETRY_BACKOFF = 0.5
RETRY_AFTER_CAP = 10.0


class SearchFailed(RuntimeError):
    """A search provider could not answer, and says why in the reader's terms.

    Distinct from "found nothing": a fallback has to know which of the two it
    is looking at. The message is built from a status and a host, never from
    the request, so it is safe to log.
    """


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

    Retryable failures (see `RETRY_STATUSES`) are attempted again before `{}` is
    returned, because "the vendor is busy" and "this document says nothing" must
    not arrive at the caller as the same answer.
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

    The last retry's reason is the one returned, so a run that ends in a 503
    says 503 rather than the first transient blip.
    """
    reason = ""
    for attempt in range(RETRY_ATTEMPTS):
        payload_out, reason, wait = _post_once(url, payload, headers, timeout)
        if not reason:
            return payload_out, ""
        if wait is None or attempt == RETRY_ATTEMPTS - 1:
            break
        # `wait == 0.0` means "retry, at our own pace"; a positive value is the
        # vendor's Retry-After, honoured as given but never above the cap.
        delay = wait or RETRY_BACKOFF * (2 ** attempt)
        log.info("%s: retrying in %.1fs (attempt %d of %d)",
                 _host(url), delay, attempt + 2, RETRY_ATTEMPTS)
        time.sleep(min(delay, RETRY_AFTER_CAP))
    return {}, reason


def _post_once(url: str, payload: dict, headers: dict,
               timeout: float) -> tuple[dict, str, float | None]:
    """One attempt: the reply, the reason it failed, and how long to wait.

    A `None` wait means do not retry; `0.0` means retry at the caller's own
    backoff; a positive value is the vendor's own `Retry-After`. A **timeout**
    is deliberately not retryable: the first attempt already spent the whole
    budget, the provider is slow rather than busy, and repeating it doubles the
    cost of learning nothing. A refused connection or a DNS failure does get a
    retry — those fail in milliseconds and are usually transient.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with network.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace")) or {}, "", None
    except urllib.error.HTTPError as error:
        # The status is diagnostic and safe; the body may quote the request.
        log.warning("%s answered HTTP %s", _host(url), error.code)
        reason = f"{_host(url)} answered HTTP {error.code}{_MEANING.get(error.code, '')}"
        if error.code not in RETRY_STATUSES:
            return {}, reason, None
        return {}, reason, _retry_after(error) or 0.0
    except TimeoutError:
        log.warning("%s timed out", _host(url))
        return {}, f"{_host(url)} did not answer within {timeout:.0f}s", None
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            log.warning("%s timed out", _host(url))
            return {}, f"{_host(url)} did not answer within {timeout:.0f}s", None
        log.warning("%s unreachable: %s", _host(url), type(error.reason).__name__)
        return {}, f"{_host(url)} unreachable ({type(error.reason).__name__})", 0.0
    except OSError as error:
        log.warning("%s unreachable: %s", _host(url), type(error).__name__)
        return {}, f"{_host(url)} unreachable ({type(error).__name__})", None
    except (json.JSONDecodeError, ValueError):
        log.warning("%s answered something that is not JSON", _host(url))
        return {}, f"{_host(url)} answered something that is not JSON", None


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    """The vendor's own `Retry-After`, in seconds, when it sent a sane one."""
    raw = ""
    try:
        raw = (error.headers.get("Retry-After") or "").strip()
    except AttributeError:
        return None
    if not raw.isdigit():
        return None
    return float(raw)


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
