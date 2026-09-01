"""The server as a child process, for the desktop shell to own.

`python -m app.web` is for a person with a terminal: it picks 8787, prints
uvicorn's banner and expects a human to open a browser. The desktop shell needs
the opposite of all three — a port nobody else can have taken, a machine-readable
line saying which one it got, and a process that dies with its parent.

**The port is chosen here, not by the shell.** A parent that finds a free port
and passes it down has already lost it by the time the child binds: something
else can take it in between, and the failure looks like a blank window. So the
sidecar binds port 0, lets the OS decide, and prints

    KRIKO_PORT <port>

as its first line of stdout. That line is the handshake, and it is why the
shell has nothing to guess.

Paths are resolved exactly as the CLI resolves them, so a pack installed in the
app is visible to `python -m app.cli` and the other way round. One store, two
front doors — the alternative (an app-private store) would silently split a
reader's knowledge base in half.
"""

import argparse
import socket
import sys

from app.web.app import create_app
from app.web.settings import Settings

#: The shell greps for this. Changing it breaks the handshake, so it is a
#: constant rather than an f-string spelled out at the call site.
PORT_LINE = "KRIKO_PORT"


def reserve(host: str, port: int) -> tuple[socket.socket, int]:
    """Bind now, hand the socket to uvicorn later.

    Binding before the announcement is the whole point: the port in the printed
    line is a port already held, not one hoped for.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    return sock, sock.getsockname()[1]


def main(argv=None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(
        prog="app.sidecar", description="the Kriko server, for a desktop shell to own"
    )
    # 127.0.0.1 for the same reason app.web binds it: there is no auth here
    # because there is nothing multi-tenant to protect, and an unauthenticated
    # pack-uninstall endpoint on 0.0.0.0 is not a preference.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 asks the OS (default)")
    parser.add_argument("--store", default=None)
    args = parser.parse_args(argv)

    overrides = {}
    if args.store:
        from pathlib import Path

        overrides["store_path"] = Path(args.store)

    sock, port = reserve(args.host, args.port)
    # Unbuffered and flushed: the shell blocks on this line, and a buffered
    # stdout in a frozen binary would look exactly like a sidecar that hung.
    print(f"{PORT_LINE} {port}", flush=True)

    # `sockets=[sock]`, not host/port and not `fd=`. Not host/port because
    # uvicorn must not rebind — the port we announced and the port it serves
    # cannot be allowed to differ. Not `fd=` because that is POSIX-only:
    # uvicorn rebuilds the socket with `socket.fromfd`, which on Windows the
    # first Windows CI run showed as the exact failure this design exists to
    # prevent — `KRIKO_PORT 58378` printed, then nothing ever listening on it.
    # A socket object needs no re-creation on any platform.
    config = uvicorn.Config(
        create_app(Settings.from_env(**overrides)),
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
