"""The browser rung: a page the plain fetch and the hosted readers both miss.

Cloudflare's hardest challenges refuse every plain HTTP client, whatever the
user agent, because they fingerprint the *browser*, not the name it gives.
The one thing that passes a browser check is a browser, and the reader
already has one installed: every machine this app ships to runs Chrome or
Edge. This module drives that browser headlessly (`--headless --dump-dom`),
so the fingerprint that answers the challenge is a genuine one, and the
page's own DOM, not a service's excerpt of it.

It is the third and last rung, tried only after `fetch.py`'s plain fetch
and `pagereader.py`'s hosted readers have both failed, and it is optional
in both directions: a machine with no browser, or one that refuses to start,
reads exactly as before, "" and no error. Nothing here is a dependency, a
download, or a second browser to maintain.

The browser is asked to identify as itself (`--user-agent` is never set):
this is the reader's own Chrome, run by the reader, reading a page the
reader asked for, and a page that answers a genuine browser with a
challenge is a page this rung has no right to trick.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

#: The rung is worth one attempt per page, and a browser takes seconds to
#: start, not milliseconds, so a hung one must not hang the run with it.
TIMEOUT = 45.0

#: A DOM past this is navigation and scripts, and `extract` truncates to
#: 12 000 characters anyway.
MAX_BYTES = 4_000_000

#: Where the browsers live when they are not on PATH. Windows first,
#: because that is where the app is installed; the two roots cover every
#: Chrome and Edge install shape (Program Files, per-user LocalAppData).
_CANDIDATE_SUBPATHS = (
    r"Google\Chrome\Application\chrome.exe",
    r"Google\Chrome Beta\Application\chrome.exe",
    r"Microsoft\Edge\Application\msedge.exe",
    r"Microsoft\Edge Beta\Application\msedge.exe",
)
_UNIX_NAMES = ("chrome", "google-chrome", "google-chrome-stable", "chromium",
               "chromium-browser", "msedge", "microsoft-edge")

#: Escape hatch, same shape as the harness table's `DIRS_ENV`: an env var
#: naming a browser binary beats every rule below, for a reader whose
#: browser is somewhere none of them predict.
BROWSER_ENV = "KRIKO_BROWSER"

_CACHE: dict[str, str] = {}


def locate() -> str:
    """The path to a browser this machine has, or "".

    Cached for the process's life: locating a browser is a filesystem walk,
    and the ladder asks for it once per refused page.
    """
    if _CACHE.get("hit", ""):
        return _CACHE["hit"]
    named = os.environ.get(BROWSER_ENV, "").strip()
    candidates: list[str] = []
    if named:
        candidates.append(named)
    for name in _UNIX_NAMES:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    home = Path.home()
    for env, subpaths in (("PROGRAMFILES", _CANDIDATE_SUBPATHS),
                          ("PROGRAMFILES(X86)", _CANDIDATE_SUBPATHS),
                          ("LOCALAPPDATA", _CANDIDATE_SUBPATHS)):
        root = os.environ.get(env)
        if not root:
            continue
        for sub in subpaths:
            candidates.append(str(Path(root) / sub))
    candidates.append(str(home / "AppData/Local/Google/Chrome/Application/chrome.exe"))
    for path in candidates:
        try:
            if path and Path(path).is_file():
                _CACHE["hit"] = path
                return path
        except OSError:
            continue
    _CACHE["hit"] = ""
    return ""


def _switches(profile: str) -> list[str]:
    return [
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=8000",
        "--dump-dom",
    ]


def read(url: str) -> str:
    """The page's DOM text through a real browser, "" when it cannot.

    "" on every failure, exactly as `fetch._download` and
    `pagereader.read`, so the ladder can fall through and the page is
    reported unread rather than half-read.
    """
    if not url.lower().startswith(("http://", "https://")):
        return ""
    browser = locate()
    if not browser:
        return ""
    import tempfile

    profile = tempfile.mkdtemp(prefix="kriko-browser-")
    try:
        done = subprocess.run(
            [browser, *_switches(profile), url], capture_output=True,
            timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    dom = done.stdout[:MAX_BYTES].decode("utf-8", "replace")
    if not dom.strip() or done.returncode != 0:
        return ""
    return dom
