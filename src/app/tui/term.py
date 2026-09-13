"""The terminal itself: raw mode, one alternate screen, and a frame differ.

**No TUI framework, deliberately.** `textual` is already declared in the
`pipeline` extra and unused, and pulling it (plus `rich`) into the *runtime*
dependencies would put a rendering framework inside the installer a reader
double-clicks, to draw four lists. `curses` is not an option at all: it is
absent on Windows, and Windows is where the reader and the harness problems
live. What is left is ANSI, which every terminal this will ever run in speaks —
Windows Terminal, conhost on Windows 10+, and every Unix emulator.

**Efficiency is the frame differ, not the drawing.** A full repaint of an
80×40 screen is 3 KB written ten times a second, which is visible as flicker on
a slow console and as wasted work everywhere. `Screen.draw` keeps the previous
frame and writes only the rows that changed, cursor-addressed — so an idle
screen writes nothing at all, and a job whose log is ticking writes one line.

Everything here is side effects on a real tty, so almost nothing in this file
is unit-testable; that is why it is *this thin*. The parts worth testing —
which key a byte sequence is, how a frame diffs — are pure functions with no
terminal in them, and `tests/test_tui.py` tests those.
"""

import os
import sys

WINDOWS = os.name == "nt"

ESC = "\x1b"
ALT_SCREEN_ON = f"{ESC}[?1049h"
ALT_SCREEN_OFF = f"{ESC}[?1049l"
CURSOR_HIDE = f"{ESC}[?25l"
CURSOR_SHOW = f"{ESC}[?25h"
CLEAR = f"{ESC}[2J"

#: Escape sequences that are one key. Kept as a table rather than a parser: the
#: set is closed (it is what terminals emit for the arrow/navigation cluster),
#: and a table is the thing a reader can check against their own terminal's
#: output with `cat -v`.
SEQUENCES = {
    "[A": "up", "[B": "down", "[C": "right", "[D": "left",
    "[H": "home", "[F": "end",
    "OA": "up", "OB": "down", "OC": "right", "OD": "left",
    "OH": "home", "OF": "end",
    "[1~": "home", "[4~": "end", "[5~": "pageup", "[6~": "pagedown",
    "[3~": "delete", "[2~": "insert",
    "[Z": "shifttab",
}

#: What a bare control byte means. `\r` and `\n` are both Enter because which
#: one arrives depends on the terminal's own line-ending setting, and a UI that
#: worked on one and not the other would be maddening to diagnose.
CONTROLS = {
    "\r": "enter", "\n": "enter", "\t": "tab", "\x7f": "backspace",
    "\x08": "backspace", " ": "space",
}


def key_for(chunk: str) -> str:
    """Name the key in `chunk`, which is one key's worth of input.

    Returns a name (`"up"`, `"enter"`, `"ctrl-c"`), a single printable
    character, or `""` for something with no meaning here. Pure, so the table
    above can be tested against real terminal output without a terminal.
    """
    if not chunk:
        return ""
    if chunk == ESC:
        return "escape"
    if chunk.startswith(ESC):
        rest = chunk[1:]
        if rest in SEQUENCES:
            return SEQUENCES[rest]
        # An unrecognised CSI is not a key; swallowing it beats typing `[15~`
        # into a filter box.
        return ""
    if chunk in CONTROLS:
        return CONTROLS[chunk]
    if len(chunk) == 1 and "\x01" <= chunk <= "\x1a":
        return f"ctrl-{chr(ord(chunk) + 96)}"
    if len(chunk) == 1 and "\x1c" <= chunk <= "\x1f":
        # The four control codes above the letters. `\x1d` is Ctrl-], which is
        # how the shell pass-through is escaped, so this branch is load-bearing
        # rather than completeness for its own sake.
        return f"ctrl-{'\\]^_'[ord(chunk) - 0x1c]}"
    if len(chunk) == 1 and chunk.isprintable():
        return chunk
    return ""


def size() -> tuple[int, int]:
    """Columns and rows, with a usable answer when there is no tty."""
    try:
        columns, lines = os.get_terminal_size()
    except OSError:
        return 80, 24
    return max(20, columns), max(6, lines)


def enable_vt() -> None:
    """Turn on ANSI interpretation for a Windows console.

    Windows 10+ consoles understand these sequences and do not act on them
    until asked. Without this the TUI renders as a page of `←[2J` on exactly
    the platform the reader is on, which is the worst possible place to find
    out. A failure here is not fatal: Windows Terminal already has it on.
    """
    if not WINDOWS:
        return
    try:
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


class RawInput:
    """Raw, unbuffered keystrokes for as long as this is entered.

    Unix puts the tty in cbreak; Windows reads through `msvcrt`, which is
    already unbuffered and needs no mode change. `read()` never blocks longer
    than `timeout`, because the render loop has a clock of its own to keep.
    """

    def __init__(self):
        self.fd = None
        self.saved = None

    def __enter__(self):
        if not WINDOWS and sys.stdin.isatty():
            import termios

            self.fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(self.fd)
            self.cbreak()
        return self

    def cbreak(self) -> None:
        """The TUI's own mode: keys arrive immediately, Ctrl-C still signals."""
        if self.fd is None:
            return
        import tty

        tty.setcbreak(self.fd)

    def raw(self) -> None:
        """The shell's mode: Ctrl-C belongs to the program on the far end.

        `cbreak` leaves `ISIG` on, so a Ctrl-C typed at a `claude` waiting for
        input would kill the TUI instead of reaching the shell — which is the
        one thing a pass-through must never do.
        """
        if self.fd is None:
            return
        import tty

        tty.setraw(self.fd)

    def __exit__(self, *exc):
        if self.fd is not None and self.saved is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        return False

    def read(self, timeout: float = 0.1) -> str:
        """One key's worth of input, or `""` if nothing arrived in time."""
        if WINDOWS:
            return self._read_windows(timeout)
        return self._read_posix(timeout)

    def _read_posix(self, timeout: float) -> str:
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return ""
        first = sys.stdin.read(1)
        if first != ESC:
            return first
        # An escape *sequence* arrives as one burst; a lone Escape key does
        # not. A tiny second wait tells them apart without making Escape feel
        # sticky.
        chunk = ESC
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.02)
            if not ready:
                break
            chunk += sys.stdin.read(1)
            if chunk[-1].isalpha() or chunk[-1] == "~":
                break
            if len(chunk) > 8:
                break
        return chunk

    def _read_windows(self, timeout: float) -> str:
        import msvcrt
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    # The extended-key prefix. The second byte is a scan code,
                    # not an ANSI sequence, so it is translated to the same
                    # names `key_for` returns for a Unix terminal — one
                    # vocabulary above this line, whatever the console below.
                    return _WINDOWS_KEYS.get(msvcrt.getwch(), "")
                return char
            time.sleep(0.005)
        return ""


#: Windows extended-key scan codes, to the names `key_for` produces elsewhere.
_WINDOWS_KEYS = {
    "H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D",
    "G": "\x1b[H", "O": "\x1b[F", "I": "\x1b[5~", "Q": "\x1b[6~",
    "S": "\x1b[3~", "R": "\x1b[2~",
}


def diff(previous: list[str], current: list[str]) -> str:
    """The smallest escape-sequence write that turns one frame into the other.

    Row-granular rather than cell-granular: a terminal write is dominated by
    the syscall, not by the bytes, so twelve cursor jumps to patch one row
    costs more than rewriting the row. An unchanged frame returns `""`, which
    is what makes an idle screen free.
    """
    out = []
    for index in range(len(current)):
        was = previous[index] if index < len(previous) else None
        if was != current[index]:
            out.append(f"{ESC}[{index + 1};1H{ESC}[2K{current[index]}")
    # The frame shrank: erase what is left behind, or the old rows stay on
    # screen looking like live content.
    for index in range(len(current), len(previous)):
        out.append(f"{ESC}[{index + 1};1H{ESC}[2K")
    return "".join(out)


class Screen:
    """An alternate screen, and the last frame drawn on it."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.previous: list[str] = []

    def __enter__(self):
        enable_vt()
        self.write(ALT_SCREEN_ON + CURSOR_HIDE + CLEAR)
        return self

    def __exit__(self, *exc):
        self.write(CURSOR_SHOW + ALT_SCREEN_OFF)
        return False

    def write(self, text: str) -> None:
        if not text:
            return
        self.stream.write(text)
        self.stream.flush()

    def draw(self, lines: list[str]) -> None:
        self.write(diff(self.previous, lines))
        self.previous = list(lines)

    def forget(self) -> None:
        """Next `draw` repaints everything.

        Used after the screen has been taken away and given back — a resize, or
        the shell handing the real terminal back — where the remembered frame
        no longer describes what is on the glass.
        """
        self.previous = []
        self.write(CLEAR)
