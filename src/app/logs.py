"""Where a shipped build says what went wrong.

Until now there was no log file anywhere. `explain_the_failure` printed
tracebacks to a stderr that only the desktop shell's boot-failure screen ever
reads, and `observability.log_analysis_jsonl` reported its failures through
`log.warning` into a `logging` system nobody had configured — so on the
machine this was written on, every analysis append had been failing for two
months into a `logs/` directory owned by another user, and nothing anywhere
said so. The call site looked correct, which is what made it survive.

Two rules come out of that, and they are the reason this module exists rather
than a `basicConfig` call in the app factory:

  * **A diagnostic lands beside the store, never in the source tree.**
    `settings.source_root()` deliberately prefers the checkout for `packs/`
    and `logs/`, because that is where a developer's *data* already is and
    moving it on upgrade would orphan it. A log is not data — it is machine
    state, and a file the reader has to be able to send us must live somewhere
    this process is known to own. So the app log is always under `KRIKO_HOME`.

  * **A path we cannot write is reported, not swallowed.** `probe()` returns
    the *reason* rather than a bool, because "cannot write" is not actionable
    and "Permission denied: /home/x/kriko/logs" is. `resolve_writable()` falls
    back rather than refusing to start: a demand-signal log is not worth a
    window that will not open, which is the fail-open rule the project already
    applies to the data path. But falling back silently is what got us here,
    so the reason is carried out to `/api/health` and shown in Settings.

Nothing here may raise. A logger that can bring down the process it is meant
to explain is worse than no logger, and this one is configured before the app
factory has a chance to fail.
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.web.settings import KRIKO_HOME

#: Rotate at a megabyte, keep three. A local app with one reader generates
#: almost nothing until something goes wrong, and when it does the interesting
#: part is the last few hundred lines — not a year of history.
MAX_BYTES = 1_000_000
BACKUPS = 3

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

#: How long to wait before trying a blocked rollover again.
ROLLOVER_RETRY_SECONDS = 60.0


class _RotatingFileHandler(RotatingFileHandler):
    """A rollover that cannot happen is skipped, never a lost line.

    Windows refuses to rename a file another process has open — a second
    Kriko, an MCP server, the test suite. The stock handler then drops the
    record, and every record after it, because each one retries the rename:
    the reader's app.log sat at 1,000,415 bytes and the 0.10.3 install that
    ran on 2026-09-27 wrote not one line into it. So a failed rename keeps
    appending to the file as it is, and tries again a minute later.
    """

    _retry_at = 0.0

    def shouldRollover(self, record):
        if time.monotonic() < self._retry_at:
            return False
        return super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            self._retry_at = time.monotonic() + ROLLOVER_RETRY_SECONDS
            if self.stream is None:
                self.stream = self._open()

#: Set once `configure()` has run, so `/api/health` can name the file and
#: Settings can offer to reveal it. `None` means logging never came up, which
#: is itself worth reporting.
_active: Path | None = None
_reason: str | None = None


def default_log_path() -> Path:
    """The app log. Overridable, because a packaged build may be sandboxed."""
    return Path(os.environ.get("KRIKO_LOG", KRIKO_HOME / "logs" / "app.log"))


def probe(path: Path) -> str | None:
    """``None`` if we can append to ``path``, else the reason we cannot.

    Actually opens the file. Checking `os.access` or the parent's mode gets
    the answer wrong on exactly the cases that matter — a directory owned by
    another user, a read-only mount, a Windows path under Program Files — and
    a probe that can be wrong is a probe nobody should trust.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"{type(exc).__name__}: {exc}"
    return None


def resolve_writable(preferred: Path, fallback: Path) -> tuple[Path, str | None]:
    """``(path_to_use, why_the_preferred_one_was_rejected)``.

    The fallback is tried too, and if it also fails the preferred path is
    returned anyway with both reasons joined: a caller that gets a path back
    can carry on being best-effort, and a caller that wants to *report* the
    state has the whole story. Returning `None` here would push the same
    silence one layer up.
    """
    why = probe(preferred)
    if why is None:
        return preferred, None
    if preferred == fallback:
        return preferred, why
    also = probe(fallback)
    if also is None:
        return fallback, why
    return preferred, f"{why} (and fallback {fallback}: {also})"


#: Set by `silence_stderr`. A module flag rather than a `configure` argument
#: because the caller who needs it is never the caller who configures: the TUI
#: owns the terminal, and the `configure` call that would smear log lines across
#: its screen happens later and deeper, inside `create_app`.
_no_stream = False


def silence_stderr() -> None:
    """Detach stderr logging, and stop `configure` re-attaching it.

    For a caller that owns the terminal. The TUI draws an alternate screen and
    diffs frames against what it believes is there; one `INFO root: logging to
    …` written underneath corrupts both halves of that — the display, and the
    differ's model of it — and the next keystroke repaints only the row it
    thinks changed, so the stray line stays until something else happens to
    redraw over it.

    The file handler is untouched. Losing the terminal is not a reason to stop
    writing `app.log`; it is the reason to.
    """
    global _no_stream
    _no_stream = True
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "stream", None) is sys.stderr:
            root.removeHandler(handler)


def configure(path: Path | None = None, level: int = logging.INFO) -> Path | None:
    """Attach a rotating file handler and a stderr handler to the root logger.

    Returns the file in use, or ``None`` if no file could be opened — in which
    case stderr is still attached, because the desktop shell captures it and
    the boot-failure screen renders it. Idempotent: calling twice does not
    double every line, which matters because the sidecar, the CLI and the app
    factory all reasonably want to be the one that sets this up.
    """
    global _active, _reason

    root = logging.getLogger()
    root.setLevel(level)

    if any(getattr(h, "_kriko", False) for h in root.handlers):
        return _active

    if not _no_stream:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(_FORMAT))
        stream._kriko = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    wanted = path or default_log_path()
    why = probe(wanted)
    if why is not None:
        _active, _reason = None, why
        root.warning("no log file: %s", why)
        return None

    try:
        handler = _RotatingFileHandler(
            wanted, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    except Exception as exc:  # pragma: no cover - probe passed, open failed
        _active, _reason = None, f"{type(exc).__name__}: {exc}"
        root.warning("no log file: %s", _reason)
        return None

    handler.setFormatter(logging.Formatter(_FORMAT))
    handler._kriko = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    _active, _reason = wanted, None
    root.info("logging to %s", wanted)
    return wanted


def active_path() -> Path | None:
    return _active


def failure_reason() -> str | None:
    return _reason


def reset_for_tests() -> None:
    """Detach our handlers. Only tests should need this."""
    global _active, _reason
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "_kriko", False)]:
        root.removeHandler(handler)
        handler.close()
    _active, _reason = None, None
