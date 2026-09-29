"""One JSON request, with the failure modes named.

Every provider below needs the same four things: a timeout, a body decoded as
JSON, an error that does not take the whole run down, and no key anywhere in
what gets logged. Written once here so a provider is only its endpoint and its
response shape.
"""

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

#: Long enough for a search or a completion, short enough that a hung provider
#: cannot make a job look stuck forever. A research run has many of these; a
#: 300-second default would let one dead host outlast the reader's patience.
TIMEOUT = 45.0


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
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
