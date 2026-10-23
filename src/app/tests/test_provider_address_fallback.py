"""An unreachable address must not consume the timeout for every DNS answer."""

import socket

import pytest

from app.providers import transport


def test_an_unreachable_family_falls_back_under_one_connection_clock(monkeypatch):
    now = [0.0]
    attempts = []
    opened = []
    rows = [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(transport.socket, "getaddrinfo", lambda *_a: rows)
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])

    class Connection:
        def __init__(self, family, *_args):
            self.family = family
            self.closed = False
            opened.append(self)

        def settimeout(self, seconds):
            self.timeout = seconds

        def connect(self, endpoint):
            attempts.append((endpoint, self.timeout))
            if self.family == socket.AF_INET:
                now[0] += self.timeout
                raise TimeoutError("unreachable")

        def close(self):
            self.closed = True

    monkeypatch.setattr(transport.socket, "socket", Connection)
    result = transport.connect(("provider.example", 443), timeout=5)
    assert result.family == socket.AF_INET6
    assert opened[0].closed
    assert [seconds for _, seconds in attempts] == [2, 2]
    assert result.timeout == 3


def test_all_addresses_share_the_timeout_instead_of_multiplying_it(monkeypatch):
    now = [0.0]
    closed = []
    rows = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", port)) for port in range(10)]
    monkeypatch.setattr(transport.socket, "getaddrinfo", lambda *_a: rows)
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])

    class Unreachable:
        def __init__(self, *_args):
            pass

        def settimeout(self, seconds):
            self.timeout = seconds

        def connect(self, _endpoint):
            now[0] += self.timeout
            raise TimeoutError("unreachable")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(transport.socket, "socket", Unreachable)
    with pytest.raises(TimeoutError, match="deadline"):
        transport.connect(("provider.example", 443), timeout=3)
    assert now[0] == 3
    assert len(closed) == 2
