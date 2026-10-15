"""Outbound HTTP with shared host limits and safe local-service routing."""

from __future__ import annotations

import ipaddress
import threading
import urllib.request
import weakref
from typing import Any
from urllib.parse import urlsplit

from app.agentresources import pace, slot

_DEFAULT_URLOPEN = urllib.request.urlopen


def _finalize_response(response: Any, permits: list[Any]) -> None:
    try:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    except Exception:
        pass
    finally:
        for permit in reversed(permits):
            try:
                permit.__exit__(None, None, None)
            except Exception:
                pass


def _loopback(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost"):
            return True
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


class _PermitResponse:
    """Response proxy that keeps its outbound slot until close/EOF."""

    def __init__(self, response: Any, permits: list[Any]) -> None:
        self._response = response
        self._permits = permits
        self._iterable = response
        self._iterator = None
        self._lock = threading.Lock()
        self._closed = False
        self._aborted = False
        self._finalizer = weakref.finalize(self, _finalize_response, response, permits)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            aborted = self._aborted
        if aborted:
            return
        try:
            exit_method = getattr(self._response, "__exit__", None)
            if exit_method is not None and getattr(self, "_entered", False):
                exit_method(None, None, None)
            else:
                close = getattr(self._response, "close", None)
                if close is not None:
                    close()
        finally:
            self._release_permits()

    def abort(self) -> None:
        """Release network permits after the caller has shut down the socket.

        Closing urllib's buffered reader from another thread can wait on the
        lock held by a blocked `readline`. `abort` is safe after the underlying
        socket has been shut down: it releases capacity now, and the reader's
        eventual unwind still performs the ordinary response close.
        """
        with self._lock:
            if self._closed or self._aborted:
                return
            self._aborted = True
        self._release_permits()

        def finish_close() -> None:
            try:
                close = getattr(self._response, "close", None)
                if close is not None:
                    close()
            except Exception:
                pass

        threading.Thread(target=finish_close, name="kriko-aborted-response-close",
                         daemon=True).start()

    def _release_permits(self) -> None:
        with self._lock:
            permits = self._permits[:]
            self._permits.clear()
            self._finalizer.detach()
        for permit in reversed(permits):
            permit.__exit__(None, None, None)

    def __enter__(self) -> "_PermitResponse":
        enter = getattr(self._response, "__enter__", None)
        if enter is not None:
            self._iterable = enter()
            self._entered = True
        try:
            self._iterator = iter(self._iterable)
        except TypeError:
            self._iterator = None
        return self

    def __exit__(self, typ: Any, value: Any, tb: Any) -> None:
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        try:
            if self._iterator is None:
                chunk = self._iterable.read(65536)
                if not chunk:
                    self.close()
                    raise StopIteration
                return chunk
            return next(self._iterator)
        except StopIteration:
            self.close()
            raise
        except BaseException:
            self.close()
            raise

    def read(self, *args: Any, **kwargs: Any):
        try:
            data = self._iterable.read(*args, **kwargs)
            if not data:
                self.close()
            return data
        except BaseException:
            self.close()
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


def urlopen(url: Any, data: Any = None, timeout: float | None = None,
            *, check=None, opener=None, kind: str = "outbound",
            pace_interval: float = 0.0):
    """Open a URL under a global+per-host quota.

    Loopback requests use an opener with proxy handling disabled, so hostile
    HTTP_PROXY settings cannot divert local model or test traffic. Remote
    requests use urllib's environment-aware opener, retaining proxy and CA
    configuration. `opener` supports deterministic tests and callers that
    already provide an explicit transport.
    """
    request = url if isinstance(url, urllib.request.Request) else None
    address = request.full_url if request is not None else str(url)
    host = (urlsplit(address).hostname or "").lower()
    if pace_interval > 0:
        pace(f"openserp:{host}", pace_interval, check=check)
    permits = [slot(kind, host, check=check)] if kind not in {"outbound", "network"} else []
    permits.append(slot("outbound", host, check=check))
    acquired = []
    try:
        for permit in permits:
            permit.__enter__()
            acquired.append(permit)
        if opener is not None:
            response = (opener(url, timeout=timeout) if data is None
                        else opener(url, data=data, timeout=timeout))
        elif _loopback(address) and urllib.request.urlopen is _DEFAULT_URLOPEN:
            no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            response = no_proxy.open(url, data=data, timeout=timeout)
        else:
            response = (urllib.request.urlopen(url, timeout=timeout) if data is None
                        else urllib.request.urlopen(url, data=data, timeout=timeout))
        return _PermitResponse(response, acquired)
    except BaseException as error:
        for permit in reversed(acquired):
            permit.__exit__(type(error), error, error.__traceback__)
        raise
