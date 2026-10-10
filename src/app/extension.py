"""Getting the browser extension onto the reader's machine.

No browser permits this outright. Chrome, Edge and Firefox all refuse to let a
native application install an extension — deliberately, because an app that
could would be an app that could read every page you open. `chrome://extensions`
cannot even be opened from a command line. The last three steps are a human's,
and no amount of code changes that.

What *is* ours is everything around them, and until now the app did none of it:
the reader had a repository to clone to get a folder to load. So this module
does the four things that are actually available —

* **stage** the extension out of the bundle into a stable path,
* **reveal** that path in the file manager,
* hand over the exact string to paste,
* and **notice when it worked**,

— and the fourth is the one that matters. `extension/background.js` calls
`127.0.0.1:8787/api/adapters`, and a browser stamps every such call with
`Origin: chrome-extension://<id>`. That is a sighting no config file can fake:
it means an installed extension, running, reaching this process. A page built
on it stops being instructions and starts being a status.

The staged copy lives in `~/.kriko/extension/` rather than inside the install
directory for one reason: Chrome remembers an unpacked extension **by path**
and drops it the moment that path disappears. An install directory is versioned
and replaced wholesale by the next installer, which would silently uninstall the
extension on every app update. `~/.kriko` outlives the binary — the same
argument that put the two SQLite files there.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: Everything the browser needs, and nothing else. An allowlist rather than a
#: copy of the directory: `tests/` is not the extension, and a folder full of
#: things Chrome will not load invites the reader to wonder which of them is
#: broken.
#:
#: It also used to exclude `colors_and_type.css` — a light cream-and-lemon
#: design system that nothing loaded, carried in the tree for months, and
#: faithfully ported into an app theme by somebody who had no way to know it
#: painted nothing. Deleted 2026-09-17. The allowlist is why it never reached
#: a browser; it is not why it survived that long.
SHIPPED = (
    "manifest.json",
    "background.js",
    "content.js",
    "hover_lite",
    "options",
    "assets",
)


#: The header the extension stamps on every request it makes to us, and the
#: oldest extension this app still knows how to answer.
#:
#: One number, in one place, bumped only when a wire change actually breaks an
#: older client — not on every extension release. The two clocks are separate
#: on purpose (knowledge weekly, the binary rarely, and the extension on its
#: own schedule again), so a *compatibility matrix* would be three moving
#: parts to keep in step and would be wrong within a release. A floor is one.
#:
#: Deliberately below the shipped version: "older than what this app carries"
#: is worth *saying* and is not a fault, because the reader may simply not
#: have reloaded the unpacked extension yet. "Older than the floor" is the
#: only case where the two ends genuinely cannot talk.
VERSION_HEADER = "x-kriko-extension"
MINIMUM_HEADER = "x-kriko-minimum-extension"
MINIMUM_VERSION = "0.3.0"
DIGEST_HEADER = "x-kriko-extension-digest"
#: The digest of the files on disk where the browser loads the extension from.
#: An extension whose own stamp differs is running files that are no longer
#: there, and reloads (B151).
STAGED_HEADER = "x-kriko-staged-digest"
_DIGEST_STAMP = re.compile(rb'const LOADED_CONTENT_DIGEST = "[a-f0-9]*";')


def parse_version(text: str) -> tuple[int, ...]:
    """A dotted version as a comparable tuple, unparseable parts dropped.

    Returns `()` for anything that is not a version — including the blank an
    extension too old to send the header leaves behind — and `()` sorts below
    every real version, which is the answer that was wanted anyway.
    """
    parts: list[int] = []
    for piece in str(text or "").split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def compatibility(running: str, shipped: str = "", *, loaded_digest: str = "",
                  carried_digest: str = "") -> dict:
    """What to say about the extension the browser is actually running.

    Three states, not two. `unknown` is separate from `too_old` because they
    call for different sentences: nothing has called us yet, versus something
    called us that we cannot answer. Collapsing them would tell a reader who
    has not installed the extension that theirs is out of date.
    """
    have = parse_version(running)
    floor = parse_version(MINIMUM_VERSION)
    if not have:
        state = "unknown"
    elif have < floor:
        state = "too_old"
    elif shipped and have < parse_version(shipped):
        state = "behind"
    elif loaded_digest and carried_digest and loaded_digest != carried_digest:
        # Same version, different files: the reader's browser ran a
        # `background.js` two releases old while this said "current" (B151).
        state = "stale_files"
    else:
        state = "current"
    return {
        "running_version": str(running or ""),
        "minimum_version": MINIMUM_VERSION,
        "state": state,
        # The app never asks the browser to do anything; it can only say what
        # it sees. So the copy is the whole remedy, and it belongs next to the
        # rule that produced it rather than in three views that drift apart.
        "detail": {
            "unknown": "",
            "too_old": (
                f"The extension in your browser is {running}, and this app "
                f"needs {MINIMUM_VERSION} or newer. Reload it from the "
                "Extension page — the copy on disk is already current."
            ),
            "behind": (
                f"The extension in your browser is {running}; this app ships "
                f"{shipped}. It still works. Reload it when convenient."
            ),
            "stale_files": (
                "The extension in your browser is running older files than "
                "this app carries. It reloads itself the next time it talks "
                "to the app; if this stays, reload it from the Extension page."
            ),
            "current": "",
        }[state],
    }


def source_dir() -> Path | None:
    """Where the extension's files are on *this* installation.

    Two shapes, as with the MCP command in `web/routers/agent.py`: frozen, the
    files were unpacked beside the code by PyInstaller; from a checkout they are
    the repository's own `extension/`. Returns None rather than raising — an app
    whose bundle was built without them should degrade to "not available here",
    not to a traceback on a page the reader opened to get help.
    """
    packaged = Path(__file__).resolve().parent / "extension_src"
    if (packaged / "manifest.json").is_file():
        return packaged
    if getattr(sys, "frozen", False):
        return None
    # …/src/app/extension.py → …/src/app → …/src → repo root
    checkout = Path(__file__).resolve().parent.parent.parent / "extension"
    return checkout if (checkout / "manifest.json").is_file() else None


def staged_dir(home: Path) -> Path:
    return home / "extension"


def version(source: Path) -> str:
    """The manifest's version, read as text rather than parsed as JSON.

    The number is for display beside "you have this loaded"; a manifest that
    does not parse is a packaging bug, and failing the status endpoint over it
    would take down the page that would have shown it.
    """
    import json

    try:
        return str(json.loads((source / "manifest.json").read_text(encoding="utf-8")).get("version", ""))
    except Exception:
        return ""


def content_files(source: Path) -> list[str]:
    files = []
    for name in SHIPPED:
        entry = source / name
        if entry.is_file():
            files.append(name)
        elif entry.is_dir():
            files.extend(path.relative_to(source).as_posix()
                         for path in sorted(entry.rglob("*")) if path.is_file())
    return sorted(files)


def firefox_manifest(content: bytes) -> bytes:
    """Derive the Firefox event-page manifest from the shared extension."""
    manifest = json.loads(content)
    manifest["background"] = {"scripts": ["background.js"]}
    manifest["browser_specific_settings"] = {"gecko": {
        "id": "kriko@kriko.local",
        "strict_min_version": "140.0",
        # Page information leaves the browser for the desktop engine, even
        # when both are on the same computer. Mozilla's definition includes it.
        "data_collection_permissions": {"required": ["browsingActivity", "websiteContent"]},
    }, "gecko_android": {"strict_min_version": "142.0"}}
    for resource in manifest.get("web_accessible_resources", []):
        resource.pop("use_dynamic_url", None)
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def content_digest(source: Path, browser: str = "chromium") -> str:
    try:
        if not (source / "manifest.json").is_file():
            return ""
        digest = hashlib.sha256()
        for name in content_files(source):
            digest.update(name.encode("utf-8") + b"\0")
            content = (source / name).read_bytes()
            if name == "manifest.json" and browser == "firefox":
                content = firefox_manifest(content)
            if name == "background.js":
                content = _DIGEST_STAMP.sub(b'const LOADED_CONTENT_DIGEST = "";', content)
            digest.update(content)
            digest.update(b"\0")
        return digest.hexdigest()
    except OSError:
        return ""


def stage(source: Path, target: Path, browser: str = "chromium") -> list[str]:
    """Copy the extension to `target`, replacing whatever is there.

    Replacing, not merging: a file the extension no longer ships must not
    survive an update, and Chrome would load the stale one without complaint.
    The directory itself is reused rather than deleted and recreated, because
    Chrome holds the *path* — recreating it under an unpacked extension that is
    currently loaded is how you get an extension pointing at an inode nothing
    else refers to.
    """
    if browser not in ("chromium", "firefox"):
        raise ValueError("Unknown extension browser")
    if source.resolve() == target.resolve() or target.resolve() in source.resolve().parents:
        raise ValueError("The source extension or its parent cannot be a staging directory")
    target.mkdir(parents=True, exist_ok=True)
    for entry in target.iterdir():  # any-order: emptying a directory, not reading it
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()

    written: list[str] = []
    for name in SHIPPED:
        src = source / name
        if not src.exists():
            continue
        dst = target / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        written.append(name)
    if browser == "firefox":
        manifest = target / "manifest.json"
        manifest.write_bytes(firefox_manifest(manifest.read_bytes()))
    background = target / "background.js"
    if background.is_file():
        stamp = f'const LOADED_CONTENT_DIGEST = "{content_digest(target)}";'.encode("ascii")
        background.write_bytes(_DIGEST_STAMP.sub(stamp, background.read_bytes()))
    return written


def target_for(store_path: Path, browser: str = "chromium") -> Path:
    """Where this installation stages the extension the browser loads."""
    base = env_override() or staged_dir(home_of(store_path))
    return base.with_name(base.name + "-firefox") if browser == "firefox" else base


def refresh(source: Path | None, target: Path, browser: str = "chromium") -> bool:
    """Restage when the app carries different files than the browser loads (B151).

    An app update replaced the carried extension and left the staged copy —
    the directory Chrome actually loads — as it was. The reader's browser ran
    the old `background.js`, which sent the listing's name and none of its
    facts, while every status on the page said "current": both ends reported
    0.3.0 and nothing compared the files. Only a copy the reader already
    staged is refreshed; staging for the first time stays their choice.
    """
    if source is None or not (target / "manifest.json").is_file():
        return False
    carried = content_digest(source, browser)
    if not carried or carried == content_digest(target):
        return False
    stage(source, target, browser)
    return True


def package(staged: Path, output: Path) -> Path:
    """Write an unsigned XPI containing only browser files, at the ZIP root."""
    import zipfile
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in content_files(staged):
            archive.write(staged / name, name)
    temporary.replace(output)
    return output


def reveal(path: Path) -> str:
    """Open `path`'s folder with `path` selected, ready to drag.

    Best-effort by design, and it returns what it tried rather than raising: a
    machine with no file manager (a headless test box, a stripped container) is
    not a failure the reader needs a red banner for — the page has already shown
    them the path, which is the part they actually need. Opening the folder
    itself is the wrong destination: dragged from inside it, there is nothing
    to drop onto the browser's extensions page.
    """
    if sys.platform.startswith("win"):
        command = ["explorer", f"/select,{path}"]
    elif sys.platform == "darwin":
        command = ["open", "-R", str(path)]
    else:
        command = ["xdg-open", str(path.parent)]
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=not sys.platform.startswith("win"),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as cause:
        return f"could not open a file manager: {cause}"
    return ""


def browsers() -> list[dict]:
    """The load screens worth naming, with the URL the reader pastes.

    Not a detection: probing for installed browsers means reading paths and
    registry keys per platform to answer a question the reader can answer by
    looking at their own taskbar. The list is short and closed — Chromium's
    extensions page and Firefox's debugging one — which is exactly the kind of
    fixed vocabulary the scalability principle allows as a constant.
    """
    return [
        {"id": "chrome", "name": "Chrome", "url": "chrome://extensions"},
        {"id": "edge", "name": "Edge", "url": "edge://extensions"},
        {"id": "brave", "name": "Brave", "url": "brave://extensions"},
        {"id": "firefox", "name": "Firefox", "url": "about:debugging#/runtime/this-firefox"},
    ]


def home_of(store_path: Path) -> Path:
    """`~/.kriko`, derived from the store rather than from `$HOME`.

    A test pointing the app at a temporary store must get a temporary extension
    directory too, or it stages into the developer's real one.
    """
    return store_path.parent


def env_override() -> Path | None:
    raw = os.environ.get("KRIKO_EXTENSION_DIR", "").strip()
    return Path(raw) if raw else None


# ── the one click that is available ──────────────────────────────────────
#
# This module's docstring says no application may install a browser extension,
# and that stands: nothing below asks a *running* browser to load anything.
#
# What it missed is the other door. A Chromium browser *we start ourselves*
# accepts `--load-extension` on its command line, so the app can hand the
# reader a window that already has Kriko in it — one click in place of stage,
# reveal, open the browser, find developer mode, drag the folder in. Four of
# those five steps were only ever there because nobody had tried the door.
#
# Two things keep it honest.
#
# **A profile of its own.** `--load-extension` passed to a browser that is
# already running does nothing whatever: the arguments are forwarded to the
# existing process, which ignores them, and the button silently accomplishes
# nothing while looking like it worked. `--user-data-dir` is what makes the
# launch a *new* browser rather than a no-op. The cost is a second profile
# with none of the reader's bookmarks or logins, so the response says so and
# the page says so before the window opens — discovering it afterwards is a
# bug report.
#
# **The check-in is the proof, not this function.** Chrome has restricted this
# flag before and will again, and a build that ignores it opens a perfectly
# ordinary window with no extension in it. So nothing here claims success: the
# extension calling `/api/adapters` is what says it worked (the page already
# watches for that sighting), and the manual steps stay on screen until it
# lands. That is the automation principle's "fail open" — offer the shortcut,
# verify it externally, never assert it.

#: The browsers Chromium ships as, per platform. A closed vocabulary of four
#: engines rather than a detection: the question is "is there a Chromium on
#: this machine", the answer is a file that exists, and reading registry keys
#: per platform to answer it would be a per-platform mechanism to maintain for
#: no more information. `shutil.which` covers a PATH install and the absolute
#: paths cover the ordinary Windows and macOS ones, which are not on PATH.
_LINUX = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
          "brave-browser", "microsoft-edge")
_MAC = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
#: `%LOCALAPPDATA%` first, and not as an afterthought: a Chrome installed by
#: someone without administrator rights — the ordinary case on a work machine —
#: lands there and never appears under `Program Files`, so a list that knows
#: only the machine-wide paths tells that reader "no Chromium here" while
#: Chrome is open in front of them. Chromium itself was missing outright, and
#: it ships its binary as `chrome.exe` too, which is why the PATH names below
#: carry both spellings.
_WINDOWS = (
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
    r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def _candidates() -> list[str]:
    """Names and paths to try, in order of "what the reader probably uses"."""
    if sys.platform.startswith("win"):
        # An unset variable expands to itself, which leaves a path that simply
        # does not exist — and `find_chromium` already drops those — so the
        # expansion needs no guard of its own.
        return [os.path.expandvars(one) for one in _WINDOWS] + [
            "chrome.exe", "chromium.exe", "msedge.exe", "brave.exe",
        ]
    if sys.platform == "darwin":
        return list(_MAC) + list(_LINUX)
    return list(_LINUX)


def find_chromium() -> str | None:
    """The first Chromium-family browser on this machine, or None.

    None is a normal answer, not a failure: a Firefox reader has no Chromium
    and the manual steps work fine for them. The caller offers the shortcut it
    can and says nothing about the one it cannot.
    """
    for candidate in _candidates():
        if os.sep in candidate or (os.altsep and os.altsep in candidate):
            if Path(candidate).is_file():
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _spawn(argv: list[str]) -> None:
    """Start the browser and forget it.

    `start_new_session` is the whole point: a browser in the sidecar's process
    group dies when the sidecar does, so closing the Kriko window would take
    the reader's browser with it mid-listing with nothing on screen to explain
    why. On Windows the same is true of the console group, and there is no
    session to leave — the shell already kills the sidecar's *tree* on exit
    (see `kriko-gpui/src/engine.rs`), which is why the browser must not be in it.
    """
    subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=not sys.platform.startswith("win"),
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            if sys.platform.startswith("win")
            else 0
        ),
    )


def launch_with_extension(
    browser: str,
    staged: Path,
    profile: Path,
    landing: str = "",
    spawn=None,
    own_profile: bool = False,
) -> str:
    """Open `browser` with the staged extension loaded. Returns "" or a reason.

    `spawn` is injected so the argument list can be asserted without starting
    a browser in the test suite — the arguments *are* the behaviour here, and
    a test that started Chrome to check them would be untestable in CI and
    unbearable locally.

    `own_profile` is for a reader whose browser already has Kriko: the landing
    page opens there, in the profile that has it, and nothing else is passed.
    Measured 2026-09-27 on Chrome 153: with every flag below, a fresh profile
    loads four built-in extensions and not Kriko — the stopgap is gone, and
    the separate window it opened was the reader's "nothing works". Their own
    Chrome had Kriko loaded unpacked from `staged` all along, and `stage` had
    just refreshed those files in place.
    """
    if not (staged / "manifest.json").is_file():
        return f"nothing staged at {staged} — the files have to be written first"

    if own_profile:
        try:
            (spawn or _spawn)([browser, landing] if landing else [browser])
        except OSError as cause:
            return f"could not start {browser}: {cause}"
        return ""

    argv = [
        browser,
        # Without this the arguments reach an already-running browser, which
        # ignores them. It is the difference between a shortcut and a no-op.
        f"--user-data-dir={profile}",
        f"--load-extension={staged}",
        # And without *this*, `--load-extension` above is ignored too.
        #
        # Chrome turned the switch off by default as an anti-malware measure:
        # the `DisableLoadExtensionCommandLineSwitch` feature makes the flag a
        # silent no-op, so the window opens, the landing page loads, and the
        # extension is simply absent. That is exactly the 0.8.0 report — "it
        # does open a chrome page with sahibinden but kriko isn't loaded" —
        # and it is the worst shape a failure can take, because everything
        # visible worked.
        #
        # Measured rather than assumed, on Chromium 141: launched with
        # `--remote-debugging-port` and the target list counted, this flag is
        # the difference between **0** `chrome-extension://` targets and
        # **2**.
        #
        # It is a stopgap and should be treated as one. The switch that
        # re-enables a switch is itself on its way out, and the durable answer
        # is a Web Store listing (B114) — this keeps the one-click path working
        # on the browsers where it still can, and the manual steps on the page
        # remain the honest fallback for where it cannot.
        "--disable-features=DisableLoadExtensionCommandLineSwitch",
        # A fresh profile otherwise opens on "make me your default browser"
        # and a sign-in wall: three dialogs between the reader and the thing
        # they pressed one button for.
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if landing:
        argv.append(landing)

    try:
        (spawn or _spawn)(argv)
    except OSError as cause:
        return f"could not start {browser}: {cause}"
    return ""


def profile_dir(home: Path) -> Path:
    """Beside the store, for the same reason the staged extension is.

    An install directory is replaced wholesale by the next installer, and a
    browser profile inside it would be discarded on every app update — taking
    with it the one thing this profile accumulates, which is the loaded
    extension's own state.
    """
    return home / "browser-profile"
