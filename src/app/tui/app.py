"""The loop: poll the engine on one thread, render and read keys on the other.

**Why a TUI for agent operations at all.** The desktop shell is for the reader
who wants to know what is wrong with a car. Agent operations have a different
audience — the person (or agent) growing the packs — and a different failure
mode: everything about them is invisible. "Research does nothing", "the
terminal says disconnected", "it reported success and kept nothing" were all
the same report, which is that the operator plane has no instruments. A window
that will not open cannot be instrumented at all, and through most of B107/B109
the reader had no working surface of any kind.

So this is a second client on the same HTTP API — not a second implementation.
Every key below is an endpoint the dashboard already calls. It needs no
webview, no WebView2, no Rust shell and no bundled JavaScript, which means it
keeps working in exactly the conditions that produced those three reports.

**Two threads, one direction.** The poller owns `state.data` and writes whole
snapshots into it; the UI thread reads them and draws. Nothing on the UI thread
blocks on HTTP, so a slow `/api/agenda` on a large store cannot make a
keystroke feel dropped — which is the difference between a tool someone uses
and one they endure. Actions are the exception and are deliberately
synchronous: pressing Enter on a research row should be over before the frame
that says it happened.
"""

import threading
from dataclasses import dataclass, field

from app.tui import screen, term
from app.tui.client import Engine, EngineError

#: How often the poller re-reads the engine. A job's log is the fastest-moving
#: thing on screen and `/api/jobs` is one indexed SELECT, so a second is
#: comfortably live without being a busy loop against a local process.
POLL_SECONDS = 1.0

#: How often the UI thread wakes to check for a key or a new snapshot. Fast
#: enough that typing never feels laggy; `Screen.draw` writes nothing when the
#: frame has not changed, so an idle TUI at this rate costs one `select` per
#: tick and no output at all.
TICK_SECONDS = 0.05

#: Leaves the shell pass-through. Ctrl-] because telnet has used it for this
#: for forty years and nothing a coding agent prints binds it.
SHELL_ESCAPE = "\x1d"


@dataclass
class State:
    engine_label: str = ""
    tab: str = "planes"
    cursor: dict = field(default_factory=dict)
    scroll: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    status: str = ""
    error: str = ""
    #: The job whose log the detail band is tailing, if any.
    following: str = ""
    running: bool = True


class Tui:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.state = State(
            engine_label=f"{engine.url}{' (own engine)' if engine.owned else ' (attached)'}"
        )
        self.state.data = {"log": {}}
        self.refresh_now = threading.Event()

    # ── the poller ──────────────────────────────────────────────────────

    def poll_once(self) -> None:
        state = self.state
        calls = {
            "planes": self.engine.planes,
            "agenda": self.engine.agenda,
            "jobs": self.engine.jobs,
            "ops": self.engine.operations,
        }
        # The current tab always, the others only when they are cheap to miss —
        # `/api/agenda` does real work, and re-running it every second while
        # the operator reads the jobs list is waste nobody asked for.
        wanted = {state.tab, "jobs"}
        # Collected, then set once. Assigning `error = ""` on each success meant
        # a failing call followed by a passing one cleared the very message it
        # had just written, and which of the two ran last was set iteration
        # order — a report that appears about half the time is worse than none.
        failures = []
        for name in sorted(wanted):
            try:
                state.data[name] = calls[name]()
            except EngineError as error:
                failures.append(f"{name}: {error}")
        state.error = "  ".join(failures)
        if state.following:
            try:
                row = self.engine.job(state.following)
                state.data.setdefault("log", {})[state.following] = row.get("log", "")
                if row.get("done"):
                    state.status = (
                        f"{state.following[:8]} {row.get('state')}: {row.get('message', '')}"
                    )
            except EngineError as error:
                state.error = str(error)

    def poll_loop(self) -> None:
        while self.state.running:
            self.poll_once()
            self.refresh_now.wait(POLL_SECONDS)
            self.refresh_now.clear()

    # ── keys ────────────────────────────────────────────────────────────

    def selected(self) -> dict | None:
        rows = screen.rows_for(self.state.tab, self.state.data)
        if not rows:
            return None
        index = max(0, min(self.state.cursor.get(self.state.tab, 0), len(rows) - 1))
        return rows[index]

    def move(self, delta: int) -> None:
        rows = screen.rows_for(self.state.tab, self.state.data)
        if not rows:
            return
        current = self.state.cursor.get(self.state.tab, 0)
        self.state.cursor[self.state.tab] = max(0, min(current + delta, len(rows) - 1))

    def act(self, key: str) -> None:
        """One keystroke. Returns nothing and sets `status`/`error` instead, so
        every path through here is visible on screen rather than in a log."""
        state = self.state
        if key in ("q", "ctrl-c"):
            state.running = False
            return
        if key in ("1", "2", "3", "4"):
            state.tab = screen.TABS[int(key) - 1]
            self.refresh_now.set()
            return
        if key in ("tab", "shifttab"):
            step = 1 if key == "tab" else -1
            state.tab = screen.TABS[(screen.TABS.index(state.tab) + step) % len(screen.TABS)]
            self.refresh_now.set()
            return
        if key in ("down", "j"):
            return self.move(1)
        if key in ("up", "k"):
            return self.move(-1)
        if key == "pagedown":
            return self.move(10)
        if key == "pageup":
            return self.move(-10)
        if key == "home":
            state.cursor[state.tab] = 0
            return
        if key == "r":
            state.status = "refreshing…"
            self.refresh_now.set()
            return
        if key == "s":
            state.status = "shell: Ctrl-] to come back"
            raise _EnterShell
        if state.tab == "agenda":
            return self._agenda_key(key)
        if state.tab == "jobs":
            return self._jobs_key(key)

    def _agenda_key(self, key: str) -> None:
        state = self.state
        if key != "enter":
            return
        row = self.selected()
        if row is None:
            return
        subject = row.get("subject_id") or ""
        if not subject:
            # `unknown_subject` rows are a message to the catalog, not a task.
            # Saying so beats starting a job that cannot mean anything.
            state.error = "this row has no subject to research — it is a gap in the catalog"
            return
        try:
            started = self.engine.research(subject, row.get("pack_id") or "")
        except EngineError as error:
            state.error = str(error)
            return
        state.status = f"research started on {subject}: {started.get('job_id', '')[:8]}"
        self._follow(started.get("job_id", ""))

    def _jobs_key(self, key: str) -> None:
        state = self.state
        row = self.selected()
        if row is None:
            return
        job_id = row.get("job_id", "")
        if key == "enter":
            self._follow(job_id, switch=False)
            state.status = f"following {job_id[:8]}"
            return
        if key == "c":
            try:
                outcome = self.engine.cancel(job_id)
            except EngineError as error:
                state.error = str(error)
                return
            state.status = f"{job_id[:8]}: {outcome.get('state', 'cancel requested')}"
            self.refresh_now.set()
            return
        if key == "R":
            try:
                started = self.engine.retry(job_id)
            except EngineError as error:
                state.error = str(error)
                return
            state.status = f"retrying as {started.get('job_id', '')[:8]}"
            self._follow(started.get("job_id", ""))

    def _follow(self, job_id: str, switch: bool = True) -> None:
        if not job_id:
            return
        self.state.following = job_id
        if switch:
            self.state.tab = "jobs"
            self.state.cursor["jobs"] = 0
        self.refresh_now.set()

    # ── the shell pass-through ──────────────────────────────────────────

    def shell(self, screen_obj, keys) -> None:
        """Hand the real terminal to the PTY until Ctrl-].

        Deliberately *not* rendered inside the TUI. Drawing a shell means
        implementing a terminal emulator — cursor addressing, scroll regions,
        colour — and there is already one running: the operator's. So the alt
        screen is dropped, the PTY's bytes go straight to stdout, and every
        escape sequence is interpreted by the thing that is best at it.

        This is the surface a harness login needs: `claude` asking for a code
        is an interactive prompt no API call can answer on its behalf, and it
        is the reason the engine has a PTY at all.
        """
        import sys

        screen_obj.__exit__()
        sys.stdout.write("\r\n" + screen.style(
            "── shell — Ctrl-] to return to kriko ──", screen.DIM) + "\r\n")
        sys.stdout.flush()
        keys.raw()
        offset = 0
        try:
            cols, rows = term.size()
            try:
                self.engine.terminal_resize(cols, rows)
            except EngineError:
                pass
            while True:
                try:
                    body = self.engine.terminal_state(offset)
                except EngineError as error:
                    sys.stdout.write(f"\r\n[engine] {error}\r\n")
                    sys.stdout.flush()
                    break
                if body.get("data"):
                    sys.stdout.write(body["data"])
                    sys.stdout.flush()
                offset = body.get("offset", offset)
                if body.get("failure"):
                    sys.stdout.write(f"\r\n[shell] {body['failure']}\r\n")
                    sys.stdout.flush()
                    break
                chunk = keys.read(0.03)
                if not chunk:
                    continue
                if SHELL_ESCAPE in chunk:
                    break
                try:
                    self.engine.terminal_input(chunk)
                except EngineError as error:
                    sys.stdout.write(f"\r\n[engine] {error}\r\n")
                    sys.stdout.flush()
                    break
        finally:
            keys.cbreak()
            screen_obj.__enter__()
            screen_obj.forget()

    # ── the loop ────────────────────────────────────────────────────────

    def run(self) -> int:
        poller = threading.Thread(target=self.poll_loop, daemon=True, name="kriko-tui-poll")
        poller.start()
        last_size = (0, 0)
        with term.Screen() as display, term.RawInput() as keys:
            while self.state.running:
                width, height = term.size()
                if (width, height) != last_size:
                    last_size = (width, height)
                    display.forget()
                display.draw(screen.render(self.state, width, height))
                chunk = keys.read(TICK_SECONDS)
                if not chunk:
                    continue
                key = term.key_for(chunk)
                if not key:
                    continue
                try:
                    self.act(key)
                except _EnterShell:
                    self.shell(display, keys)
                except EngineError as error:  # pragma: no cover - belt
                    self.state.error = str(error)
        return 0


class _EnterShell(Exception):
    """`act` asking the loop for the terminal, which only the loop can give."""


def main(url: str = "", allow_start: bool = True, settings=None) -> int:
    from app import logs
    from app.tui.client import connect

    # Before anything that might log. When no engine is running this starts one
    # in-process, and `create_app` calls `logs.configure()` — whose stderr
    # handler writes straight onto the alternate screen this is about to draw,
    # under a frame differ that will not know to repaint over it. The file
    # handler stays: losing the terminal is the reason to keep `app.log`, not a
    # reason to stop.
    logs.silence_stderr()
    try:
        engine = connect(url, allow_start=allow_start, settings=settings)
    except EngineError as error:
        print(f"kriko tui: {error}")
        return 1
    tui = Tui(engine)
    try:
        return tui.run()
    finally:
        tui.state.running = False
        tui.refresh_now.set()
