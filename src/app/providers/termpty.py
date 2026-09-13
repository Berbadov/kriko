"""One PTY, and a transcript anyone can catch up on.

**Why a transcript and not a socket.** The terminal used to be a WebSocket:
the PTY's bytes went out on the wire as they were read and were never kept,
so a client that was not connected at that instant lost them, and a client
that could not connect at all learned nothing. Six releases (0.7.4-0.7.11)
were spent making that socket explain itself, and the reader's last report
was still close code `1006` — the browser's "the opening handshake never
finished", from a layer below anything the handler could reach. Meanwhile
every other live view in this app (`/api/jobs/{id}/stream`) is Server-Sent
Events over ordinary HTTP, and those work on the reader's machine.

So the PTY now owns its own output. A reader thread drains it into a bounded
buffer the moment it is produced — connected or not — and every consumer asks
the same question, "what came after byte N?", over whatever transport it likes.
That inverts the failure: a transport that breaks loses *latency*, not
*output*, and the next reader to connect sees the scrollback including whatever
the shell printed as it died. The reason a session failed is a field on the
session rather than a frame someone had to be listening for.

The buffer is bounded (`SCROLLBACK`) because a `yes` left running must not grow
a local process without limit; a consumer whose offset has fallen off the back
is told so rather than silently skipped.
"""

import os
import sys
import threading

WINDOWS = sys.platform == "win32"

#: How much output one session keeps. Enough that a reader who opens the panel
#: after a command finished still sees it; small enough that a runaway writer
#: costs a bounded amount of memory.
SCROLLBACK = 256 * 1024


class TermSession:
    """A shell on a pty, its transcript, and why it stopped.

    Every attribute is read under `_lock` by threads that did not create the
    session: the reader thread appends, HTTP handlers snapshot, and the
    process's lifetime is longer than any one request's.
    """

    def __init__(self, scrollback: int = SCROLLBACK):
        self.proc = None
        self.scrollback = scrollback
        self._lock = threading.Lock()
        self._buffer = ""
        #: Total bytes ever produced, *including* what has fallen off the back.
        #: A consumer's cursor is an offset into this, never into `_buffer`.
        self._produced = 0
        self._reader: threading.Thread | None = None
        self._generation = 0
        self.failure: str = ""
        self.ended = False

    # ── lifetime ────────────────────────────────────────────────────────

    def start(self, cols: int = 80, rows: int = 24) -> None:
        """Spawn the shell, unless one is already running.

        A failure here is raised *and* recorded: the caller is an HTTP request
        that can answer with it, and a consumer who connects a second later
        gets the same reason from `state()` rather than an empty screen.
        """
        if self.proc is not None and self.alive():
            return
        home = os.path.expanduser("~")
        try:
            if WINDOWS:
                import winpty

                shell = os.environ.get("COMSPEC", "powershell.exe")
                proc = winpty.PtyProcess.spawn(
                    shell, cwd=home, dimensions=(rows, cols)
                )
            else:
                import ptyprocess

                shell = os.environ.get("SHELL", "/bin/sh")
                proc = ptyprocess.PtyProcess.spawn(
                    [shell], cwd=home, dimensions=(rows, cols)
                )
        except Exception as exc:
            self._fail(f"{type(exc).__name__}: {exc}")
            raise
        with self._lock:
            self.proc = proc
            self.failure = ""
            self.ended = False
            self._generation += 1
            generation = self._generation
        self._reader = threading.Thread(
            target=self._pump, args=(proc, generation), daemon=True,
            name="kriko-term-reader",
        )
        self._reader.start()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.isalive()

    def close(self) -> None:
        """Kill the shell, *then* release the pty — in that order.

        The reader thread is parked in a blocking `read()` on this fd, and
        closing the fd out from under it deadlocks: `ptyprocess.close()` waits
        for a descriptor the reader is still holding. Killing the child first
        makes that read return EOF, which is what lets the thread leave.
        """
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        self._end()
        try:
            proc.terminate(force=True)
        except Exception:
            pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=5.0)
            if reader.is_alive():
                # Still parked. It is a daemon thread on a dead child; letting
                # it be costs a thread, while closing the fd under it costs the
                # process.
                return
        try:
            proc.close(force=True)
        except Exception:
            pass

    # ── the reader thread ───────────────────────────────────────────────

    def _pump(self, proc, generation: int) -> None:
        """Drain the pty for as long as it lives.

        Runs whether or not anyone is watching — that is the whole point. The
        `generation` check keeps a thread belonging to a previous, restarted
        session from writing into the current one's transcript.
        """
        while True:
            try:
                chunk = proc.read(65536)
            except (EOFError, OSError) as exc:
                self._fail(f"{type(exc).__name__}: {exc}", generation)
                return
            except Exception as exc:  # pragma: no cover - defensive
                self._fail(f"{type(exc).__name__}: {exc}", generation)
                return
            if not chunk:
                self._end(generation)
                return
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", "replace")
            self._append(chunk, generation)

    def _append(self, text: str, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self._buffer += text
            self._produced += len(text)
            if len(self._buffer) > self.scrollback:
                self._buffer = self._buffer[-self.scrollback :]

    def _fail(self, reason: str, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self.failure = reason
            self.ended = True

    def _end(self, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self._generation:
                return
            self.ended = True

    # ── what a consumer asks ────────────────────────────────────────────

    def state(self) -> dict:
        with self._lock:
            return {
                "offset": self._produced,
                "running": self.proc is not None and not self.ended,
                "ended": self.ended,
                "failure": self.failure,
            }

    def since(self, offset: int) -> tuple[str, int, bool]:
        """Output after byte `offset`, the new offset, and whether we dropped.

        `dropped` is true when the requested offset has already fallen off the
        back of the scrollback — the consumer is handed what is left and told
        that there is a hole, rather than being silently re-synced.
        """
        with self._lock:
            start = self._produced - len(self._buffer)
            if offset >= self._produced:
                return "", self._produced, False
            if offset < start:
                return self._buffer, self._produced, True
            return self._buffer[offset - start :], self._produced, False

    # ── what a consumer sends ───────────────────────────────────────────

    def write(self, data: str) -> None:
        if self.proc is None:
            raise RuntimeError("terminal is not running")
        self.proc.write(data if WINDOWS else data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        if self.proc is None:
            return
        self.proc.setwinsize(rows, cols)


SESSION = TermSession()
