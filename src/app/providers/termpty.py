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
import time

WINDOWS = sys.platform == "win32"

#: How much output one session keeps. Enough that a reader who opens the panel
#: after a command finished still sees it; small enough that a runaway writer
#: costs a bounded amount of memory.
SCROLLBACK = 256 * 1024

#: How long the reader waits when the shell is alive and has said nothing.
#: Only Windows ever gets here (see `_pump`); short enough to feel instant,
#: long enough that an idle prompt is not a busy loop.
IDLE_SECONDS = 0.02


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
        #: Which shell was spawned, for the failure message. "EOFError: Pty is
        #: closed" does not say whether COMSPEC resolved to something sane.
        self.shell: str = ""
        #: Held across the whole of `start`. The check-and-spawn was not atomic,
        #: and the panel calls `/stream` and `/resize` at the same moment on
        #: mount — two threads could both find no process and both spawn one,
        #: leaving an orphaned shell nobody reads and nobody kills.
        self._spawning = threading.Lock()

    # ── lifetime ────────────────────────────────────────────────────────

    def start(self, cols: int = 80, rows: int = 24) -> None:
        """Spawn the shell, unless one is already running.

        A failure here is raised *and* recorded: the caller is an HTTP request
        that can answer with it, and a consumer who connects a second later
        gets the same reason from `state()` rather than an empty screen.
        """
        with self._spawning:
            self._start_locked(cols, rows)

    def _start_locked(self, cols: int, rows: int) -> None:
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
            self.shell = shell
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

    def restart(self, cols: int = 80, rows: int = 24) -> None:
        """Throw away the shell and its transcript, and start again.

        Typing `exit` is an ordinary thing to do, and until this existed it
        ended the terminal for the life of the app: the session stayed
        `ended`, `/stream` returned at once, and the panel had nothing to
        offer but the message. A shell you cannot restart is not a shell.

        The transcript goes with it, deliberately. Keeping the old one would
        mean the new shell's first prompt arrives below a dead one's output
        with nothing marking the join, and the client's byte offset would be
        pointing into a session that no longer exists.
        """
        self.close()
        with self._lock:
            self._buffer = ""
            self._produced = 0
            self.failure = ""
            self.ended = False
        self.start(cols=cols, rows=rows)

    # ── the reader thread ───────────────────────────────────────────────

    def _pump(self, proc, generation: int) -> None:
        """Drain the pty for as long as it lives.

        Runs whether or not anyone is watching — that is the whole point. The
        `generation` check keeps a thread belonging to a previous, restarted
        session from writing into the current one's transcript.

        **An empty read is not end-of-file, and assuming it was is what broke
        Windows.** `ptyprocess.read()` blocks until there is something and
        raises `EOFError` at the end, so on POSIX an empty return never happens
        and treating it as the end is harmless. `pywinpty` does not work that
        way: its `read()` comes back with `''` the moment there is nothing to
        say yet, which on a freshly spawned shell is immediately — before
        `cmd.exe` has written its first byte. This loop then called `_end()`,
        the session was marked finished, and the next read raised
        `EOFError: Pty is closed`, which is exactly the report from the 0.8.0
        install: a terminal that ends before it starts, on Windows only, having
        worked under a real pty on Linux.

        So the question an empty read asks is `isalive()`, not "are we done".
        One loop serves both platforms, because on POSIX the branch is simply
        never taken.
        """
        while True:
            try:
                chunk = proc.read(65536)
            except (EOFError, OSError) as exc:
                # The shell going away is ordinary — someone typed `exit`. It
                # is only a *failure* if it never lived long enough to speak.
                self._finish(proc, generation, f"{type(exc).__name__}: {exc}")
                return
            except Exception as exc:  # pragma: no cover - defensive
                self._fail(f"{type(exc).__name__}: {exc}", generation)
                return
            if chunk:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", "replace")
                self._append(chunk, generation)
                continue
            if not self._still_alive(proc):
                self._finish(proc, generation, "")
                return
            # Alive and quiet. Sleeping here rather than spinning: this is a
            # background thread for the life of the process, and a busy loop
            # would cost a core for a shell sitting at its prompt.
            time.sleep(IDLE_SECONDS)

    @staticmethod
    def _still_alive(proc) -> bool:
        try:
            return bool(proc.isalive())
        except Exception:  # pragma: no cover - a closed pty answers by raising
            return False

    def _finish(self, proc, generation: int, raised: str) -> None:
        """Record how the shell ended, and whether that counts as a failure.

        A shell that ran and then exited is not an error — it is `exit`. A shell
        that never produced a byte is, and the difference is the whole of what
        the reader needs to know. `EOFError: Pty is closed` on its own said
        neither, which is why the first Windows report could not be acted on.
        """
        with self._lock:
            if generation != self._generation:
                return
            spoke = self._produced > 0
            status = getattr(proc, "exitstatus", None)
        detail = f"{self.shell or 'the shell'}"
        if status is not None:
            detail += f" exited with status {status}"
        else:
            detail += " ended"
        if spoke:
            self._end(generation)
            return
        self._fail(f"{detail} without producing any output"
                   + (f" ({raised})" if raised else ""), generation)

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
