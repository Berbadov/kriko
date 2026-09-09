"""The engine outlives the window, and only *Quit* ends it.

Until 0.5.1 the rule in `main.rs` was "nothing outlives the app": closing the
window killed the sidecar. That made the browser extension unusable in the one
situation it exists for — the reader is on a listing page, not looking at
Kriko — because the extension talks to `EXTENSION_PORT` on a process the X
button had just killed. So the window now hides and a tray icon holds the
process.

Inverting that invariant moves a real hazard rather than removing it. An
engine nobody can see is an engine nobody can stop: it holds the store's WAL
lock into the next launch, and on Windows it keeps its own `kriko-sidecar.exe`
mapped, which is exactly the "Error opening file for writing" that fails the
*next* installer. Four things have to be simultaneously true for the trade to
be safe, and each is a test below:

* **The tray exists, and it has a Quit.** A tray that only reopens the window
  is a process with no off switch. It is built in `setup` with `?`, so a shell
  that cannot build one fails to start instead of failing the first time the
  reader presses X.
* **Quit kills the engine before it exits.** `--exit-with-parent` would get
  there on its own once stdin closes, but "eventually" is long enough for the
  next install to fail.
* **Every other exit path still kills it.** The dock, a session logout,
  `app.restart()` after an update — none destroys a window.
* **The installer stops both binaries, shell first.** Killing `Kriko.exe`
  closes the sidecar's stdin, which is the engine's own designed exit; the
  second `taskkill` is for a sidecar that did not take it.

None of this can be compiled here — there is no Rust toolchain on any machine
that touches this tree, and the first thing to find out would be a Windows
bundle build. So these read the source, the same way `test_desktop_update.py`
and `test_shell_is_locked.py` already do.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CRATE = REPO / "tauri" / "src-tauri"


def _code(path: Path) -> str:
    """The file with `//` comments stripped.

    Every assertion here is about what the shell *does*, and this file is
    heavily commented with the very identifiers it asserts on — a gate that a
    comment can satisfy is not a gate.
    """
    return "\n".join(
        re.sub(r"//.*$", "", line) for line in path.read_text(encoding="utf-8").splitlines()
    )


@pytest.fixture(scope="module")
def main_rs() -> str:
    return _code(CRATE / "src" / "main.rs")


@pytest.fixture(scope="module")
def nsh() -> str:
    return _code(CRATE / "installer.nsh")


def _block(source: str, opener: str, after: int = 0) -> str:
    """The brace-balanced block that starts at the first `opener` past `after`."""
    start = source.index(opener, after)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unbalanced braces after {opener!r}")


def _arm(source: str, pattern: str) -> str:
    """The body of the match arm whose pattern starts at `pattern`.

    Not `_block`: a match pattern can itself carry braces
    (`CloseRequested { api, .. }`), and those balance before the body starts.
    """
    start = source.index(pattern)
    return _block(source, "=>", start)


def test_closing_the_window_hides_it_rather_than_ending_the_process(main_rs):
    arm = _arm(main_rs, "tauri::WindowEvent::CloseRequested")
    assert "api.prevent_close()" in arm, "the X button must not close the window"
    assert re.search(r"window\.hide\(\)", arm), "prevented but not hidden leaves a dead window up"
    assert "kill_engine" not in arm, (
        "the whole point of the tray is that the engine survives the window; "
        "killing it here restores the defect"
    )


def test_the_reader_is_told_once_that_the_engine_is_still_running(main_rs):
    arm = _arm(main_rs, "tauri::WindowEvent::CloseRequested")
    assert "hint_still_running" in arm, (
        "a window that vanishes with no explanation reads as a crash, and the "
        "reader has no reason to look near the clock"
    )
    hint = _block(main_rs, "fn hint_still_running")
    assert re.search(r"engine\.hinted\.lock\(\)", hint), "nothing records that it was shown"
    assert re.search(r"if \*hinted\s*\{\s*return", hint) and "*hinted = true" in hint, (
        "once per process, not once per close: a dialog on every X is the "
        "kind of nag that gets an app uninstalled"
    )


def test_the_tray_menu_can_both_open_and_quit(main_rs):
    tray = _block(main_rs, "fn build_tray")
    for item in ("open", "quit"):
        assert re.search(rf'MenuItem::with_id\(\s*app,\s*"{item}"', tray), f"no {item} item"
    assert re.search(r"Menu::with_items\(\s*app,\s*&\[&open,\s*&quit\]", tray), (
        "both items have to reach the menu; a tray with no Quit is a process "
        "the reader cannot stop"
    )


def test_quit_kills_the_engine_before_it_exits(main_rs):
    tray = _block(main_rs, "fn build_tray")
    kill = tray.index("kill_engine")
    exit_ = tray.index("app.exit(")
    assert kill < exit_, (
        "exiting first leaves the sidecar to notice its stdin closed, and the "
        "next installer fails on a still-mapped kriko-sidecar.exe"
    )


def test_a_left_click_on_the_tray_brings_the_window_back(main_rs):
    tray = _block(main_rs, "fn build_tray")
    assert "on_tray_icon_event" in tray
    click = _block(tray, "on_tray_icon_event")
    assert "show_window" in click, "clicking the icon must reopen the app"
    assert "show_menu_on_left_click(false)" in tray, (
        "otherwise a left click opens a menu instead of the window it is for"
    )


def test_show_window_unminimizes_as_well_as_shows(main_rs):
    show = _block(main_rs, "fn show_window")
    assert "unminimize" in show, (
        "a hidden-while-minimized window shows again still minimized, which "
        "looks exactly like the tray doing nothing"
    )


def test_the_tray_is_built_during_setup_and_a_failure_stops_the_launch(main_rs):
    setup = _block(main_rs, ".setup(")
    assert "build_tray(app.handle())?" in setup, (
        "built without `?`, a tray that failed to appear would be discovered "
        "the first time the reader pressed X — with no way back to the app"
    )
    assert setup.index("build_tray") < setup.index("offer_update"), (
        "the way out of the app comes before the offer to replace it"
    )


def test_every_other_exit_path_still_kills_the_engine(main_rs):
    run = _block(main_rs, ".run(")
    assert "tauri::RunEvent::Exit" in run and "kill_engine" in run, (
        "a dock quit, a logout or a post-update restart destroys no window; "
        "without this backstop each one leaves an orphan holding the WAL lock"
    )


def test_the_tray_feature_is_enabled(main_rs):
    manifest = tomllib.loads((CRATE / "Cargo.toml").read_text(encoding="utf-8"))
    features = manifest["dependencies"]["tauri"]["features"]
    assert "tray-icon" in features, (
        "without the feature the tray code does not compile, and the only "
        "machine that would find out is the release runner"
    )


@pytest.mark.parametrize("hook", ["NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL"])
def test_the_installer_stops_the_shell_before_the_sidecar(hook, nsh):
    macro = nsh[nsh.index(f"!macro {hook}") :]
    macro = macro[: macro.index("!macroend")]
    shell = macro.find("/IM Kriko.exe")
    sidecar = macro.find("/IM kriko-sidecar.exe")
    assert shell != -1, f"{hook} does not stop the shell"
    assert sidecar != -1, f"{hook} does not stop the engine"
    assert shell < sidecar, (
        "shell first: killing it closes the sidecar's stdin, which is the "
        "engine's own designed exit and the only one that unwinds cleanly"
    )
    assert macro.count("/T") >= 2, (
        "PyInstaller onefile re-execs, so the pid we spawned is a bootloader "
        "and the child is what holds the image mapped"
    )
