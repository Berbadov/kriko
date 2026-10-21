"""The MCP server on a local URL, for the chat clients that cannot spawn one.

Most clients start Kriko themselves and talk over stdio, which needs no port
and is the default. A few take only a URL (a hosted-style client pointed at
your own machine, a browser tool, a container). For those the same tools are
served over streamable HTTP, and the one rule that matters is where it
listens: **127.0.0.1, always.** There is no host option to get wrong, no
`0.0.0.0`, and a request whose `Host` or `Origin` is not this machine is
refused, so a web page open in the reader's browser cannot drive their store
through DNS rebinding either. The store is the reader's own; this is a second
door onto the same machine, not onto the network.

The port is fixed, not chosen by the OS, for the reason the extension's is:
a client configured once cannot be told a random number. If it is taken, the
server says so and exits rather than moving, because a config that points at
a port something else answers is the failure that looks exactly like success.
"""

from __future__ import annotations

HOST = "127.0.0.1"
#: Next to the extension's 8787, and no one else's well-known port.
PORT = 8788
PATH = "/mcp"

_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def url(port: int = PORT) -> str:
    return f"http://{HOST}:{port}{PATH}"


def configure(server, port: int = PORT) -> None:
    """Point `server` at loopback, with DNS-rebinding protection on."""
    from mcp.server.transport_security import TransportSecuritySettings

    if not 1 <= int(port) <= 65535:
        raise ValueError(f"the MCP port must be between 1 and 65535, not {port}")
    server.settings.host = HOST
    server.settings.port = int(port)
    server.settings.streamable_http_path = PATH
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(_ALLOWED_HOSTS),
        allowed_origins=list(_ALLOWED_ORIGINS),
    )


def serve(server, port: int = PORT) -> int:
    """Serve until interrupted. Returns a process exit code."""
    import socket
    import sys

    configure(server, port)
    # Say so before uvicorn would: it reports a taken port as a stack trace
    # in a log nobody reads, and this process has no window to show it in.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, int(port)))
    except OSError as error:
        print(f"kriko mcp: {url(port)} is not available ({error}). "
              f"Another Kriko may already serve it; pass --mcp-port to use another.",
              file=sys.stderr, flush=True)
        return 1
    finally:
        probe.close()
    print(f"kriko mcp: serving {url(port)} (this machine only)",
          file=sys.stderr, flush=True)
    server.run("streamable-http")
    return 0
