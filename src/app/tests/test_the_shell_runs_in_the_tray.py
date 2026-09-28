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

None of this can be *type*-checked here: a real `cargo check` wants the
crate's dependencies and, on Linux, `webkit2gtk`, which is not installed. So
these read the source, the same way `test_desktop_update.py` and
`test_shell_is_locked.py` already do.

Until 2026-09-10 this paragraph claimed something stronger and false — that no
machine touching this tree had a Rust toolchain at all. It was taken as
settled rather than re-checked, and the cost was exact: `main.rs` shipped in
B83 with three adjacent string literals and no `concat!`, which is a parse
error, and all twelve tests below went green on it because each one only asks
whether a *string* is present. Code that does not compile still contains its
strings. `test_the_shell_is_valid_rust.py` now parses every `.rs` with
`rustc`, which needs no dependencies and no system libraries, and skips only
where there is genuinely no `rustc` to run.
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
    assert "kill_engine" not in arm, (
        "the whole point of the tray is that the engine survives the window; "
        "killing it here restores the defect"
    )
    # B152.3: the page draws the notice and answers; the shell hides on "hide",
    # and hides anyway when the page never answers (a hung page is no excuse
    # for a window that will not close).
    assert "ask_page_to_close" in arm, "the close has to reach the page's own box"
    ask = _block(main_rs, "fn ask_page_to_close")
    assert re.search(r"close_answered\.load", ask) and re.search(r"\.hide\(\)", ask), (
        "an unanswered close leaves a window that cannot be closed"
    )
    answer = _block(main_rs, "fn window_answer")
    assert re.search(r'"hide"\s*=>\s*\{[^}]*\.hide\(\)', answer), "the page said hide; nothing hid"


def test_the_reader_is_told_in_the_apps_own_box_not_an_os_dialog(main_rs):
    # "more stylised warning box; and please no OS warning sound." A native
    # message dialog is the sound; the notice lives in CloseNotice.svelte, with
    # its "Don't show this again" remembered by the app, not the shell.
    arm = _arm(main_rs, "tauri::WindowEvent::CloseRequested")
    ask = _block(main_rs, "fn ask_page_to_close")
    assert "__krikoClose" in ask
    assert ".dialog()" not in arm + ask, (
        "an OS dialog plays the system sound the reader asked to lose"
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


# ── the console, as a thing you double-click ────────────────────────────

def _nsis_code(text: str) -> str:
    """`installer.nsh` with its comments removed.

    NSIS comments with `;`, and `_code` above only strips `//` — so every
    assertion below would otherwise be satisfiable by the paragraph of prose
    that explains it. That is the exact failure this file's own docstring
    warns about, one comment syntax over.
    """
    return "\n".join(
        line.split(";", 1)[0] for line in text.splitlines()
    )


def _macro(text: str, name: str) -> str:
    body = text[text.index(f"!macro {name}") :]
    return body[: body.index("!macroend")]


def test_the_installer_makes_the_console_a_thing_you_double_click(nsh):
    """One click, from the Start menu, into the operator console.

    The console exists because a window would not open on the reader's machine.
    An entry point of "find a terminal, find the install directory, remember a
    flag" is not an answer to that — so the installer puts a shortcut next to
    the app's own, pointing at the sidecar Tauri already ships, with `--tui`.

    No second artifact: `kriko-sidecar.exe` is the externalBin the bundle
    installs anyway, and `app/tui/` is already frozen inside it.
    """
    code = _nsis_code(nsh)
    install = _macro(code, "NSIS_HOOK_POSTINSTALL")
    assert "CreateShortcut" in install, "nothing creates the console shortcut"
    assert "kriko-sidecar.exe" in install, (
        "the shortcut must point at the binary the bundle actually installs"
    )
    assert '"--tui"' in install, (
        "without the flag the shortcut starts a headless engine and shows "
        "the reader a console that says nothing"
    )


def test_uninstalling_takes_the_console_shortcut_with_it(nsh):
    """A Start-menu entry that outlives its target is a click that does
    nothing, on a machine whose owner already decided to be rid of us."""
    code = _nsis_code(nsh)
    removed = _macro(code, "NSIS_HOOK_POSTUNINSTALL")
    assert "Delete" in removed and "Kriko Console.lnk" in removed


def test_the_console_shortcut_names_the_same_link_both_ways(nsh):
    """Created and deleted under one name, or the uninstall misses it."""
    code = _nsis_code(nsh)
    created = _macro(code, "NSIS_HOOK_POSTINSTALL")
    removed = _macro(code, "NSIS_HOOK_POSTUNINSTALL")
    link = "Kriko Console.lnk"
    assert link in created and link in removed
