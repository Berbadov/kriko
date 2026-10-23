"""urllib connections with a bounded fallback across DNS addresses."""

import http.client
import socket
import time
import urllib.request


CONNECT_ATTEMPT_SECONDS = 2.0


def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    # socket.create_connection gives *each* address the full timeout. A host
    # with eight unreachable IPv6 answers can exhaust a turn before IPv4 is
    # tried. Alternate families and give all attempts one clock.
    host, port = address
    seconds = socket.getdefaulttimeout() if timeout is socket._GLOBAL_DEFAULT_TIMEOUT else timeout
    ends = None if seconds is None else time.monotonic() + seconds
    rows = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    ipv4 = [row for row in rows if row[0] == socket.AF_INET]
    ipv6 = [row for row in rows if row[0] == socket.AF_INET6]
    ordered = []
    for index in range(max(len(ipv4), len(ipv6))):
        if index < len(ipv4):
            ordered.append(ipv4[index])
        if index < len(ipv6):
            ordered.append(ipv6[index])
    ordered.extend(row for row in rows if row[0] not in (socket.AF_INET, socket.AF_INET6))
    error = OSError("host resolved to no usable addresses")
    for family, kind, protocol, _name, endpoint in ordered:
        left = None if ends is None else ends - time.monotonic()
        if left is not None and left <= 0:
            raise TimeoutError("connection deadline ended")
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(CONNECT_ATTEMPT_SECONDS if left is None else min(CONNECT_ATTEMPT_SECONDS, left))
            if source_address:
                connection.bind(source_address)
            connection.connect(endpoint)
            connection.settimeout(None if ends is None else max(0.001, ends - time.monotonic()))
            return connection
        except OSError as exc:
            error = exc
            connection.close()
    raise error


class HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect


class HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect


class HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(HTTPConnection, request)


class HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(HTTPSConnection, request, context=self._context)


def opener(*handlers):
    # Keep urllib's proxy, redirect, authentication and TLS verification rules.
    return urllib.request.build_opener(HTTPHandler(), HTTPSHandler(), *handlers)
