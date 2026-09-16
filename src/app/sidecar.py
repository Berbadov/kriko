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

**It answers on two sockets, and only one of them is guessable.** The random
port is for the shell, which is told it. The Chrome extension cannot be told
anything — it has no filesystem and no channel from the window — so it
hardcodes `EXTENSION_PORT`, and the sidecar binds that too when it is free. One
server, two doors; if the port is taken (a second Kriko, or a `python -m
app.web` in a terminal) the extension door is simply skipped and the app is
unaffected.

**It is also how an agent reaches an installed app.** `--mcp` runs the MCP
stdio server (`app/mcp_server.py`) instead of the HTTP one, out of the same
binary and against the same `~/.kriko`. Without it the research protocol existed
only for someone with a source checkout: a reader who installed the app had a
*Research* button that produces a brief and nothing able to act on it. The two
modes share this file rather than shipping a second executable because they must
resolve the store identically — an agent writing to a different SQLite file than
the window reads is the one failure that would look like success.

**It dies with its parent, and that is code, not a hope.** With
`--exit-with-parent` the sidecar watches its own stdin: the write end of that
pipe lives in the shell, so the shell going away — cleanly, crashed, or killed
— is an EOF here. The orphan this prevents is not theoretical. On Windows a
surviving sidecar keeps its own `.exe` mapped, and the *installer* is what
fails: "Error opening file for writing: kriko-sidecar.exe", with no hint that a
process from the last run is the cause.

Paths are resolved exactly as the CLI resolves them, so a pack installed in the
app is visible to `python -m app.cli` and the other way round. One store, two
front doors — the alternative (an app-private store) would silently split a
reader's knowledge base in half.
"""

import argparse
import os
import socket
import sys
import threading

from app.web.app import create_app
from app.web.settings import EXTENSION_PORT, Settings

#: The shell greps for this. Changing it breaks the handshake, so it is a
#: constant rather than an f-string spelled out at the call site.
PORT_LINE = "KRIKO_PORT"
#: Printed for the second socket, when there is one. Deliberately does not
#: contain PORT_LINE as a substring: the shell takes the first line that does.
EXTRA_LINE = "KRIKO_EXTENSION_PORT"


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


#: How long a shutdown asked for politely gets before the process is ended
#: outright. uvicorn drains connections on `should_exit`, but a request stuck
#: mid-download would otherwise keep the whole binary — and, on Windows, the
#: lock on its own file — alive long after the window closed.
GRACE_SECONDS = 5.0


def exit_when_parent_goes(server, stream=None, grace: float = GRACE_SECONDS):
    """Stop `server` when our stdin closes.

    A daemon thread, so it can never itself be the reason the process lingers.
    The read is blocking and that is the point: it costs nothing until the pipe
    closes, and it needs no polling of a parent pid the OS may already have
    recycled.
    """

    def watch() -> None:
        pipe = stream if stream is not None else getattr(sys.stdin, "buffer", sys.stdin)
        try:
            while pipe.read(1):
                pass
        except Exception:
            pass  # a closed or unreadable pipe means the same thing as EOF
        server.should_exit = True
        # Asked politely above, ended here. `os._exit` rather than `sys.exit`:
        # this is a daemon thread, and SystemExit raised in one exits nothing.
        threading.Event().wait(grace)
        os._exit(0)

    thread = threading.Thread(target=watch, name="parent-watchdog", daemon=True)
    thread.start()
    return thread


def serve_mcp(store=None) -> int:
    """Hand stdin/stdout to the MCP server and get out of the way.

    No port, no handshake, no parent watchdog: stdin *is* the transport here, so
    the watchdog would consume the very bytes it is meant to outlive, and EOF on
    it already ends the process the way MCP intends.
    """
    from app import mcp_server

    if store is not None:
        mcp_server.STORE_PATH = store
    mcp_server.mcp.run()
    return 0


def also_reserve(host: str, port: int):
    """Bind a second, fixed port — or don't, and say so.

    Never fatal. This socket is a convenience for a client that cannot be told
    a random number; the app has already got the port it needs by the time this
    runs, and a taken 8787 must not be the reason a window fails to open.
    """
    if not port:
        return None
    try:
        sock, _ = reserve(host, port)
        return sock
    except OSError as error:
        print(
            f"the extension port {port} is not available ({error}); the Chrome "
            f"extension will not find this instance",
            file=sys.stderr,
            flush=True,
        )
        return None


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
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="run the MCP stdio server instead of the HTTP one, on the same store",
    )
    # The operator console, out of the binary the installer already ships.
    #
    # `app/tui/` is in the wheel and therefore already frozen into this
    # executable, so this flag costs one branch and adds no build artifact —
    # and it is what makes the console *standalone*: a reader with no Python,
    # no Node and no working WebView2 can still drive research, watch a job and
    # open a shell, by running the same .exe with one argument. Given that a
    # webview which would not open is the reason this console exists, having
    # its only entry point require a source checkout would have been a joke.
    parser.add_argument(
        "--tui",
        action="store_true",
        help="run the operator console in this terminal, on the same store",
    )
    # Off by default: `python -m app.sidecar < /dev/null` in a terminal would
    # otherwise read EOF at once and exit. The desktop shell always passes it.
    parser.add_argument(
        "--extension-port",
        type=int,
        default=EXTENSION_PORT,
        help="fixed second port for the browser extension; 0 disables it",
    )
    parser.add_argument(
        "--exit-with-parent",
        action="store_true",
        help="exit when stdin closes, i.e. when whatever spawned us goes away",
    )
    # The one thing this process cannot work out for itself. A supervised
    # sidecar and a hand-run one are identical over HTTP — same endpoints,
    # same ports — and the only difference is whether anything is reading the
    # stdout that `KRIKO_FOCUS` goes out on. So the shell declares it, and
    # /api/focus stops claiming it raised a window nobody was listening for.
    parser.add_argument(
        "--supervised",
        action="store_true",
        help="a desktop shell is reading our stdout and can raise a window",
    )
    args = parser.parse_args(argv)

    # Before the store, before the bind: whatever happens next has somewhere
    # to be written down. The shell captures our stderr only until the window
    # opens, so a failure five minutes in used to reach nobody at all.
    #
    # Except in MCP mode, which owns stdio — a StreamHandler on stderr is
    # harmless there (the protocol is on stdout) and is left in place, but the
    # file is what matters and it is configured the same way.
    from app import logs

    # In console mode, *before* `configure` rather than inside the TUI. The
    # TUI's own `silence_stderr()` runs too late from here: `configure` has
    # already attached the handler and already logged "logging to …", so the
    # frozen binary's first line of output was a log line printed over the
    # reader's terminal. Found by running the frozen console under a pty, which
    # is the only place it could have been found — every test passes either way.
    if args.tui:
        logs.silence_stderr()

    logs.configure()

    # Before the store, before the routers, before anything that could read a
    # key: `~/.kriko/env` into this process's environment. The provider
    # adapters in `app/providers/` read `os.environ` — the same way they did
    # when a shell was the only way to set a key — so this one call is what
    # makes a double-clicked app able to use the paid research plane at all.
    # It never overwrites, so an exported variable still wins; see app/keys.py.
    from app import keys as keyfile

    loaded = keyfile.load()
    if loaded and not args.tui:
        # The count, never the names' values. A log line is the last place a
        # key should be able to reach.
        #
        # Not in console mode: this is a bare `print`, so no logging handler
        # can suppress it, and it would land on the reader's terminal a moment
        # before the console draws over it. The console has a Planes tab that
        # says what is configured; it does not need a banner.
        print(f"loaded {len(loaded)} API key(s) from {keyfile.env_path()}",
              file=sys.stderr, flush=True)

    store = None
    if args.store:
        from pathlib import Path

        store = Path(args.store)

    # Before anything binds: the MCP mode owns stdio and must print nothing of
    # its own on it. A stray handshake line here would be a protocol error.
    if args.mcp:
        return serve_mcp(store)

    # And the console owns the *terminal*, which is the same rule one layer up:
    # it attaches to a running app on EXTENSION_PORT if there is one — sharing
    # its engine, store and jobs — and otherwise starts an engine of its own in
    # this process. Either way nothing here should bind a port first, so this
    # returns before `reserve`.
    if args.tui:
        from app.tui import main as run_tui

        settings = Settings(store_path=store) if store is not None else None
        return run_tui(settings=settings)

    overrides = {}
    if store is not None:
        overrides["store_path"] = store

    sock, port = reserve(args.host, args.port)
    # Unbuffered and flushed: the shell blocks on this line, and a buffered
    # stdout in a frozen binary would look exactly like a sidecar that hung.
    print(f"{PORT_LINE} {port}", flush=True)

    # After the handshake, never before: this bind can fail, and the line the
    # shell is blocking on must not be behind anything that can go wrong.
    extra = also_reserve(args.host, args.extension_port)
    if extra is not None:
        print(f"{EXTRA_LINE} {extra.getsockname()[1]}", flush=True)
    # Through the environment rather than an override, because `Settings` is
    # built from the environment a few lines down and this is the one fact
    # about the running process that no configuration file could supply.
    os.environ["KRIKO_EXTENSION_BOUND"] = "1" if extra is not None else "0"
    # Same route, same reason: a fact about this process's *supervision*, not
    # a configuration choice, so it travels the same way the port bind does.
    os.environ["KRIKO_SUPERVISED"] = "1" if args.supervised else "0"

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
        # uvicorn's default `log_config` calls `logging.config.dictConfig`,
        # which gives its own "uvicorn"/"uvicorn.error"/"uvicorn.access"
        # loggers their own stderr handler and sets "uvicorn" to
        # `propagate=False` — so an unhandled exception in any route (an
        # ASGI-level "Exception in ASGI application" traceback, logged
        # through "uvicorn.error") stops at that handler and never reaches
        # the root logger `app.logs.configure()` set up above, which is the
        # only thing writing to `~/.kriko/logs/app.log`. It still prints to
        # stderr, but nothing reads stderr once the shell's window has
        # opened (see the module docstring), so the traceback is not lost —
        # it is gone. `None` here skips that dictConfig call entirely, so
        # "uvicorn.error" keeps its default `propagate=True` and no handler
        # of its own, and the exception reaches app.log like everything
        # else's. `log_level` still applies: it sets these loggers' level
        # independently of `log_config`, so `warning` is unchanged.
        log_config=None,
    )
    server = uvicorn.Server(config)
    if args.exit_with_parent:
        exit_when_parent_goes(server)
    server.run(sockets=[s for s in (sock, extra) if s is not None])
    return 0


if __name__ == "__main__":
    sys.exit(main())
