"""The operator console, tested where it can be: keys, frames, and the API.

Three seams, and they are chosen so that almost nothing is untested by being
untestable:

* `term.key_for` and `term.diff` are pure. A terminal's escape sequences are
  data, and the frame differ is the whole efficiency claim — both belong under
  assertions rather than under someone's eyes.
* `screen.render` is a pure function of state. Every layout decision is here,
  so "does the harness path appear on the planes tab" is a unit test rather
  than a screenshot.
* `Tui.act` is keystroke → API call, with a fake engine underneath. That is
  where the behaviour lives.

What is not tested is `term.Screen` and `RawInput`, which are `tcsetattr` and
writes to a real tty. They are kept tiny for exactly that reason — the B89
lesson is that a test which can only assert a string is present proves very
little, so the answer is to have less code it cannot reach, not more tests
that pretend.

The end-to-end case at the bottom runs the real client against a real engine
over a real socket, which is the check that the API this TUI claims to use is
the API the app actually serves.
"""

import threading

import pytest

from app.tui import client, screen, term
from app.tui.app import State, Tui


# ── keys ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "chunk,expected",
    [
        ("\x1b[A", "up"),
        ("\x1b[B", "down"),
        ("\x1bOA", "up"),          # application cursor mode — same key
        ("\x1b[6~", "pagedown"),
        ("\x1b", "escape"),
        ("\r", "enter"),
        ("\n", "enter"),
        ("\x03", "ctrl-c"),
        ("\x1d", "ctrl-]"),
        ("q", "q"),
        ("\x1b[99~", ""),          # unknown CSI is not a keystroke
        ("", ""),
    ],
)
def test_a_byte_sequence_names_one_key(chunk, expected):
    assert term.key_for(chunk) == expected


# ── the frame differ ────────────────────────────────────────────────────

def test_an_unchanged_frame_writes_nothing():
    """The efficiency claim, as an assertion. An idle console costs no output
    at all — which is what lets the render loop tick twenty times a second."""
    frame = ["one", "two", "three"]
    assert term.diff(frame, list(frame)) == ""


def test_only_the_changed_row_is_rewritten():
    written = term.diff(["one", "two", "three"], ["one", "TWO", "three"])
    assert "TWO" in written
    assert "one" not in written and "three" not in written
    # Addressed to row 2, not redrawn from the top.
    assert written.startswith(f"{term.ESC}[2;1H")


def test_a_shorter_frame_erases_what_it_left_behind():
    written = term.diff(["one", "two", "three"], ["one"])
    assert written.count("[2K") == 2  # rows 2 and 3 cleared


# ── the frame ───────────────────────────────────────────────────────────

def _state(**kwargs) -> State:
    state = State(engine_label="http://127.0.0.1:8787 (attached)")
    state.data = {"log": {}}
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


def _plain(lines: list[str]) -> str:
    """The frame with its colour taken off, for matching on text."""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(lines))


def test_the_frame_fits_the_terminal_it_was_given():
    state = _state()
    lines = screen.render(state, 80, 24)
    assert len(lines) <= 24
    assert all(len(_plain([line])) <= 80 for line in lines)


def test_the_planes_tab_names_the_binary_that_was_found():
    """The screen exists for this fact.

    "Agent operations do nothing" is usually `locate()` finding no CLI, and the
    only thing that distinguishes it from "the CLI ran and found nothing" is
    whether a path is on screen. B108.
    """
    state = _state(tab="planes")
    state.data["planes"] = {
        "default": "harness",
        "planes": [{
            "id": "harness", "ready": True, "cost_basis": "subscription",
            "what": "drive the coding agent you already pay for",
            "harnesses": [{"id": "claude-code", "label": "Claude Code",
                           "command": "claude",
                           "path": "/home/me/.local/bin/claude"}],
            "unusable": [], "looked_for": ["claude", "opencode"],
        }],
    }
    text = _plain(screen.render(state, 100, 24))
    assert "/home/me/.local/bin/claude" in text


def test_a_harness_that_was_never_found_says_where_it_looked():
    """An empty list is not an answer. "No CLI found" is only actionable if the
    operator can see it looked in the wrong place."""
    state = _state(tab="planes", cursor={"planes": 1})
    state.data["planes"] = {
        "default": "agent",
        "planes": [{
            "id": "harness", "ready": False, "cost_basis": "subscription",
            "what": "", "harnesses": [], "unusable": [],
            "looked_for": ["claude", "opencode"],
        }],
    }
    text = _plain(screen.render(state, 100, 24))
    assert "claude, opencode" in text
    # The remedy is in the detail band rather than the row, because the band
    # wraps and a row truncates — and a truncated remedy is not a remedy.
    assert "KRIKO_HARNESS_DIRS" in text


def test_an_empty_tab_explains_itself_instead_of_showing_nothing():
    text = _plain(screen.render(_state(tab="jobs"), 80, 24))
    assert "no jobs yet" in text


def test_the_selected_row_is_the_one_the_cursor_is_on():
    state = _state(tab="jobs", cursor={"jobs": 1})
    state.data["jobs"] = {"items": [
        {"job_id": "a" * 12, "kind": "research", "state": "succeeded", "message": "first"},
        {"job_id": "b" * 12, "kind": "research", "state": "failed", "message": "second"},
    ]}
    lines = screen.render(state, 90, 24)
    marked = [line for line in lines if line.startswith(f"{term.ESC}[34m▸")]
    assert len(marked) == 1
    assert "second" in _plain(marked)


def test_the_detail_band_tails_the_log_rather_than_heading_it():
    """A job's log is interesting at the end. Showing the first ten lines of a
    forty-line run is showing the setup and hiding the outcome."""
    state = _state(tab="jobs", cursor={"jobs": 0})
    state.data["jobs"] = {"items": [{"job_id": "j1", "kind": "research",
                                     "state": "running", "message": ""}]}
    state.data["log"] = {"j1": "\n".join(f"line {n}" for n in range(40))}
    text = _plain(screen.render(state, 80, 30))
    assert "line 39" in text
    assert "line 0\n" not in text


def test_a_long_row_is_truncated_not_wrapped_into_the_next_row():
    state = _state(tab="agenda", cursor={"agenda": 0})
    state.data["agenda"] = {"rows": [
        {"kind": "thin_subject", "asked": 3, "label": "x" * 400, "subject_id": "s1",
         "why": "research this"},
    ]}
    lines = screen.render(state, 60, 20)
    assert all(len(_plain([line])) <= 60 for line in lines)


# ── keystrokes, against a fake engine ───────────────────────────────────

class FakeEngine:
    url = "http://127.0.0.1:0"
    owned = False

    def __init__(self):
        self.calls = []

    def _note(self, name, *args):
        self.calls.append((name, *args))

    def planes(self):
        self._note("planes")
        return {"planes": [], "default": ""}

    def agenda(self, limit=60):
        self._note("agenda")
        return {"rows": []}

    def jobs(self, limit=60):
        self._note("jobs")
        return {"items": []}

    def job(self, job_id):
        self._note("job", job_id)
        return {"job_id": job_id, "log": "working\n", "done": False, "state": "running"}

    def research(self, subject_id, pack_id="", backend=""):
        self._note("research", subject_id, pack_id)
        return {"job_id": "new-job-id"}

    def agenda_run(self):
        self._note("agenda_run")
        return {"job_id": "agenda-job"}

    def cancel(self, job_id):
        self._note("cancel", job_id)
        return {"state": "cancelling"}

    def retry(self, job_id):
        self._note("retry", job_id)
        return {"job_id": "retry-job"}

    def operations(self, limit=200):
        self._note("operations")
        return {"items": []}


def _tui() -> Tui:
    return Tui(FakeEngine())


def test_the_number_keys_switch_tabs():
    tui = _tui()
    tui.act("2")
    assert tui.state.tab == "agenda"
    tui.act("3")
    assert tui.state.tab == "jobs"
    tui.act("4")
    assert tui.state.tab == "ops"


def test_the_ops_tab_shows_the_live_operations_feed():
    """The TUI's whole reason to exist now: a second client on the same feed
    the app dashboard renders (B111/AGENT_OPERATIONS). Before this, the
    console had no view of agent-driven work at all — the operator could see
    jobs but not an MCP-door `submit_findings` mid-flight."""
    state = _state(tab="ops")
    state.data["ops"] = {"items": [
        {"op_id": 1, "door": "mcp", "kind": "research", "name": "submit_findings",
         "state": "running", "subject_id": "s1", "pack_id": "org.kriko.cars",
         "started_at": "2026-09-16T10:00:00Z", "usd": 0.03, "tokens": None},
    ]}
    text = _plain(screen.render(state, 100, 24))
    assert "submit_findings" in text
    assert "mcp" in text
    assert "$0.03" in text


def test_an_empty_ops_tab_explains_itself():
    text = _plain(screen.render(_state(tab="ops"), 80, 24))
    assert "no operations recorded" in text


def test_the_poller_asks_for_operations_on_the_ops_tab():
    tui = _tui()
    tui.state.tab = "ops"
    tui.poll_once()
    assert ("operations",) in tui.engine.calls


def test_q_stops_the_loop():
    tui = _tui()
    tui.act("q")
    assert tui.state.running is False


def test_the_cursor_cannot_leave_the_list():
    tui = _tui()
    tui.state.tab = "jobs"
    tui.state.data["jobs"] = {"items": [{"job_id": "a", "state": "queued"},
                                        {"job_id": "b", "state": "queued"}]}
    for _ in range(5):
        tui.act("down")
    assert tui.state.cursor["jobs"] == 1
    for _ in range(5):
        tui.act("up")
    assert tui.state.cursor["jobs"] == 0


def test_enter_on_an_agenda_row_starts_research_and_follows_it():
    tui = _tui()
    tui.state.tab = "agenda"
    tui.state.data["agenda"] = {"rows": [
        {"kind": "thin_subject", "subject_id": "s1", "pack_id": "p1", "asked": 2,
         "label": "a subject", "why": "…"},
    ]}
    tui.act("enter")
    assert ("research", "s1", "p1") in tui.engine.calls
    assert tui.state.following == "new-job-id"
    assert tui.state.tab == "jobs"


def test_enter_on_a_catalog_gap_refuses_instead_of_starting_a_meaningless_job():
    """`unknown_subject` rows have no subject id — they are a message to the
    catalog. Starting a job on one would succeed at nothing."""
    tui = _tui()
    tui.state.tab = "agenda"
    tui.state.data["agenda"] = {"rows": [
        {"kind": "unknown_subject", "subject_id": "", "identity": "{...}", "asked": 9,
         "label": "", "why": "…"},
    ]}
    tui.act("enter")
    assert not any(call[0] == "research" for call in tui.engine.calls)
    assert "no subject" in tui.state.error


def test_a_failed_action_is_reported_on_screen_rather_than_raised():
    """A TUI that dies on an HTTP error is a TUI that loses the error with it."""
    tui = _tui()
    tui.state.tab = "agenda"
    tui.state.data["agenda"] = {"rows": [
        {"kind": "thin_subject", "subject_id": "s1", "asked": 1, "label": "x", "why": ""},
    ]}

    def boom(*args, **kwargs):
        raise client.EngineError("no research plane can run")

    tui.engine.research = boom
    tui.act("enter")
    assert "no research plane" in tui.state.error
    assert tui.state.running is True
    assert "no research plane" in _plain(screen.render(tui.state, 80, 24))


def test_cancel_and_retry_reach_the_engine():
    tui = _tui()
    tui.state.tab = "jobs"
    tui.state.data["jobs"] = {"items": [{"job_id": "j1", "kind": "research",
                                         "state": "running", "message": ""}]}
    tui.act("c")
    assert ("cancel", "j1") in tui.engine.calls
    tui.act("R")
    assert ("retry", "j1") in tui.engine.calls
    assert tui.state.following == "retry-job"


def test_the_poller_reads_the_followed_jobs_log():
    tui = _tui()
    tui.state.following = "j1"
    tui.poll_once()
    assert tui.state.data["log"]["j1"] == "working\n"


def test_a_polling_failure_lands_in_the_status_bar_not_in_a_traceback():
    tui = _tui()

    def boom(*args, **kwargs):
        raise client.EngineError("connection refused")

    tui.engine.jobs = boom
    tui.poll_once()
    assert "connection refused" in tui.state.error


# ── against a real engine ───────────────────────────────────────────────

def test_the_client_speaks_to_the_app_this_repo_actually_serves(tmp_path):
    """The endpoints this TUI is built on are the ones the app serves.

    A fake engine proves the keystrokes; this proves the contract. Run over a
    real socket, against `create_app`, so a renamed route or a changed response
    shape fails here rather than on the operator's machine.
    """
    import socket

    import uvicorn

    from app.web.app import create_app
    from app.web.settings import Settings

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    ))
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        engine = client.Engine(f"http://127.0.0.1:{port}")
        for _ in range(100):
            if client.reachable(engine.url):
                break
            threading.Event().wait(0.05)
        else:
            pytest.fail("the test engine never answered /api/health")

        assert "planes" in engine.planes()
        assert "rows" in engine.agenda()
        assert "items" in engine.jobs()
        assert "items" in engine.operations()
        # The screen renders real payloads, not just the shapes invented above.
        state = _state(tab="planes")
        state.data["planes"] = engine.planes()
        assert screen.render(state, 100, 30)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_attach_returns_nothing_when_no_engine_is_serving(monkeypatch):
    """And, crucially, does not start one. `connect` owns that decision, so a
    caller who wants "attach or fail" can have it without the side effect."""
    monkeypatch.setattr(client, "reachable", lambda url: False)
    monkeypatch.delenv("KRIKO_URL", raising=False)
    assert client.attach() is None


def test_an_explicit_url_that_does_not_answer_is_an_error_not_a_new_engine(monkeypatch):
    """Starting a *different* engine would hide both a typo and a dead app, and
    quietly point the operator at the wrong store."""
    monkeypatch.setattr(client, "reachable", lambda url: False)
    with pytest.raises(client.EngineError, match="nothing is serving"):
        client.connect("http://127.0.0.1:9", allow_start=True)


# ── standalone: no Python, no webview, no checkout ──────────────────────

def test_the_frozen_binary_runs_the_console_without_binding_a_port(monkeypatch):
    """`kriko-sidecar.exe --tui` is the console, standalone.

    `app/tui/` is already in the wheel and therefore already inside the frozen
    binary the installer ships, so this flag costs one branch and no build
    artifact — and it is the whole of what "standalone" means here: a machine
    with no Python, no Node and no working WebView2 can still drive research,
    watch a job and open a shell.

    It must return *before* `reserve`: the console attaches to a running app if
    there is one and otherwise starts an engine in-process, so a sidecar that
    bound a port first would be a second engine nobody asked for.
    """
    from app import sidecar

    called = {}

    def fake_tui(**kwargs):
        called.update(kwargs)
        return 0

    def never(*args, **kwargs):
        raise AssertionError("--tui bound a port before handing over to the console")

    monkeypatch.setattr("app.tui.main", fake_tui)
    monkeypatch.setattr(sidecar, "reserve", never)
    assert sidecar.main(["--tui"]) == 0
    assert called == {"settings": None}


def test_the_console_passes_an_explicit_store_through(monkeypatch, tmp_path):
    from app import sidecar

    seen = {}
    monkeypatch.setattr("app.tui.main", lambda **kw: seen.update(kw) or 0)
    monkeypatch.setattr(sidecar, "reserve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    sidecar.main(["--tui", "--store", str(tmp_path / "other.sqlite")])
    assert seen["settings"].store_path == tmp_path / "other.sqlite"


def test_the_console_stops_log_lines_reaching_the_screen():
    """The bug this would have shipped with.

    When nothing is serving, the console starts an engine in-process — and
    `create_app` calls `logs.configure()`, whose stderr handler writes straight
    onto the alternate screen, underneath a frame differ that will not know to
    repaint over it. The stray line then stays until something else happens to
    redraw that row.

    The file handler must survive: losing the terminal is the reason to keep
    `app.log`, not a reason to stop.
    """
    import logging
    import sys

    from app import logs

    root = logging.getLogger()
    saved, saved_flag = list(root.handlers), logs._no_stream
    try:
        root.handlers = []
        stream = logging.StreamHandler(sys.stderr)
        root.addHandler(stream)
        logs.silence_stderr()
        assert stream not in root.handlers

        # And `configure` must not put one back afterwards.
        logs.configure(path=None)
        assert not any(getattr(h, "stream", None) is sys.stderr for h in root.handlers)
    finally:
        root.handlers = saved
        logs._no_stream = saved_flag


def test_kriko_is_a_command_rather_than_an_incantation():
    """Every document written for someone who installed the wheel says
    `kriko tui`. Without this entry point that is a lie, and the true form
    (`python -m app.cli tui`) only works from a checkout."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["kriko"] == "app.cli:main"


# ── what running the frozen binary found ────────────────────────────────

def test_a_narrow_terminal_still_gets_a_readable_header():
    """Found under a pty that reported no window size, which clamps to 20
    columns. `pad` sliced with a negative width — which slices from the *end* —
    so a 17-character title rendered as its first character, and the header was
    a bare URL. A terminal that reports nothing is exactly the case nobody
    tests by looking at it."""
    state = _state()
    state.engine_label = "http://127.0.0.1:40201 (own engine)"
    lines = screen.render(state, 20, 10)
    text = _plain(lines)
    assert "kriko" in text, "the name is the first thing to keep, not the URL"
    assert all(len(_plain([line])) <= 20 for line in lines)


def test_pad_never_slices_backwards():
    assert screen.pad("a title", 0) == ""
    assert screen.pad("a title", -16) == ""
    assert screen.pad("a title", 1) == "a"
    assert screen.pad("a title", 4) == "a t…"
    assert screen.pad("ab", 5) == "ab   "


def test_the_console_mode_silences_logging_before_it_can_print(monkeypatch):
    """The frozen binary's first line of output was a log line.

    `app.tui.main` calls `silence_stderr()`, but from `app.sidecar` that is too
    late: `logs.configure()` has already attached the handler *and* already
    logged "logging to …". So the sidecar has to silence it before configuring,
    and the order is what this holds.
    """
    from app import sidecar

    order = []
    monkeypatch.setattr("app.logs.silence_stderr", lambda: order.append("silence"))
    monkeypatch.setattr("app.logs.configure", lambda *a, **k: order.append("configure"))
    monkeypatch.setattr("app.tui.main", lambda **kw: 0)
    monkeypatch.setattr(sidecar, "reserve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    sidecar.main(["--tui"])
    assert order == ["silence", "configure"]


def test_the_key_banner_is_not_printed_over_the_console(monkeypatch, capsys):
    """A bare `print` to stderr, which no logging handler can suppress. It
    would land on the reader's terminal a moment before the console draws."""
    from app import sidecar

    monkeypatch.setattr("app.logs.silence_stderr", lambda: None)
    monkeypatch.setattr("app.logs.configure", lambda *a, **k: None)
    monkeypatch.setattr("app.keys.load", lambda: {"EXA_API_KEY": "x"})
    monkeypatch.setattr("app.tui.main", lambda **kw: 0)
    monkeypatch.setattr(sidecar, "reserve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    sidecar.main(["--tui"])
    assert "API key(s)" not in capsys.readouterr().err
