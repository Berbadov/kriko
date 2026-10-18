"""The engine outlives the window, and only *Quit* ends it.

The rule in the desktop app is "closing the window hides it". Closing used to
kill the sidecar, which made the browser extension unusable in the one
situation it exists for: the reader is on a listing page, not looking at Kriko,
and the extension talks to `EXTENSION_PORT` on a process the X button had just
killed. So the window hides and a tray icon holds the process.

Inverting that invariant moves a real hazard rather than removing it. An engine
nobody can see is an engine nobody can stop: it holds the store's WAL lock into
the next launch, and on Windows it keeps its own `kriko-sidecar.exe` mapped,
which is exactly the "Error opening file for writing" that fails the *next*
installer. Each of these has to be simultaneously true for the trade to be
safe, and each is a test below:

* **The tray exists and has a Quit.** A tray that only reopens the window is a
  process with no off switch. If it cannot be built, closing quits instead:
  a hidden window with no way back is a process nobody can find.
* **Quit stops the engine before the app exits.** `--exit-with-parent` gets
  there on its own once stdin closes, but "eventually" is long enough for the
  next install to fail.
* **Every other exit path still stops it.** A keyboard quit, the engine's own
  `quit` answer, a logout: none goes through the tray.
* **One Kriko per machine.** A second launch raises the first and exits before
  it starts a second engine.

None of this is type-checked here (`cargo check` in `kriko-ui/src-tauri` does
that), so these read the source with comments stripped.
`test_the_shell_is_valid_rust.py` parses every `.rs`, so a string present in
code that does not compile does not pass unnoticed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

CRATE = Path(__file__).resolve().parents[3] / "kriko-ui" / "src-tauri"


def _code(name: str) -> str:
    """The file with `//` comments stripped: a comment is not behaviour."""
    path = CRATE / "src" / name
    return "\n".join(
        re.sub(r"//.*$", "", line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _block(source: str, opener: str) -> str:
    """The brace-balanced block starting at the first `{` after `opener`."""
    start = source.index("{", source.index(opener))
    depth = 0
    for i in range(start, len(source)):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return source[start : i + 1]
    raise AssertionError(f"unbalanced braces after {opener!r}")


@pytest.fixture(scope="module")
def lib_rs() -> str:
    return _code("lib.rs")


@pytest.fixture(scope="module")
def shell_rs() -> str:
    return _code("shell.rs")


def test_closing_the_window_hides_it_rather_than_ending_the_process(lib_rs):
    close = _block(lib_rs, "= event")
    hiding = close.split("else")[0]
    assert "shell::can_hide()" in hiding and "shell::hide_window" in hiding
    assert "api.prevent_close()" in hiding, "without this the window closes"
    assert "engine::stop" not in hiding, (
        "the whole point of the tray is that the engine survives the window; "
        "stopping it here restores the defect"
    )


def test_without_a_tray_closing_quits_instead_of_stranding_the_engine(lib_rs, shell_rs):
    close = _block(lib_rs, "= event")
    fallback = close.split("else", 1)[1]
    assert "engine::stop()" in fallback and "prevent_close" not in fallback, (
        "a hidden window with no tray is a process nobody can find"
    )
    can_hide = _block(shell_rs, "fn can_hide")
    assert "TRAY" in can_hide, "hiding is allowed without a tray"
    build = _block(shell_rs, "fn build_tray")
    assert "TRAY.store(true" in build and "Ok(())" in build, (
        "the tray flag must be set only when the tray was actually built"
    )
    assert build.index("builder.build(app)?") < build.index("TRAY.store(true"), (
        "the flag is set before the tray exists"
    )


def test_the_tray_menu_can_both_open_and_quit(shell_rs):
    for item in ("open", "quit"):
        assert re.search(rf'MenuItem::with_id\(\s*app,\s*"{item}"', shell_rs), f"no {item} item"
    assert re.search(r"Menu::with_items\(\s*app,\s*&\[&open,\s*&quit_item\]", shell_rs), (
        "both items have to reach the menu; a tray with no Quit is a process "
        "the reader cannot stop"
    )
    assert '"open" => show_window(app)' in shell_rs and '"quit" => quit(app)' in shell_rs


def test_quit_stops_the_engine_before_it_ends_the_app(shell_rs):
    quit_ = _block(shell_rs, "pub fn quit(")
    assert quit_.index("engine::stop()") < quit_.index("app.exit(0)"), (
        "ending the app first leaves the sidecar to notice its stdin closed, "
        "and the next installer fails on a still-mapped kriko-sidecar.exe"
    )


def test_a_left_click_on_the_tray_brings_the_window_back(shell_rs):
    assert "MouseButton::Left" in shell_rs and "show_window(tray.app_handle())" in shell_rs
    assert "show_menu_on_left_click(false)" in shell_rs, (
        "otherwise a left click opens a menu instead of the window it is for"
    )


def test_showing_the_window_restores_it_when_minimised(shell_rs):
    show = _block(shell_rs, "pub fn show_window")
    assert "unminimize()" in show and "show()" in show and "set_focus()" in show, (
        "a hidden-while-minimised window shows again still minimised, which "
        "looks exactly like the tray doing nothing"
    )


def test_every_other_exit_path_still_stops_the_engine(lib_rs):
    run = _block(lib_rs, "RunEvent::Exit")
    assert "engine::stop()" in run, (
        "a keyboard quit or a logout goes through no tray; without this "
        "backstop each one leaves an orphan holding the WAL lock"
    )


def test_the_tray_exists_before_the_engine_starts(lib_rs):
    assert lib_rs.index("shell::build_tray(") < lib_rs.index("engine::start("), (
        "a window that can hide must have somewhere to come back from"
    )


def test_a_second_launch_raises_the_first_before_starting_an_engine(lib_rs):
    run = lib_rs[lib_rs.index("pub fn run()") :]
    assert "tauri_plugin_single_instance::init" in run and "shell::show_window(app)" in run, (
        "a second launch must raise the first instead of starting its own"
    )
    assert run.index("tauri_plugin_single_instance::init") < run.index("engine::start("), (
        "starting the engine first gives the second launch an engine of its "
        "own, holding the store the first one needs"
    )


def test_the_tray_and_the_single_instance_dependencies_are_declared():
    manifest = tomllib.loads((CRATE / "Cargo.toml").read_text(encoding="utf-8"))
    deps = manifest["dependencies"]
    assert "tray-icon" in deps["tauri"]["features"], (
        "without the feature the tray code does not compile, and the only "
        "machine that would find out is the one building the installer"
    )
    assert "tauri-plugin-single-instance" in deps


def test_a_release_build_opens_no_console():
    """Without the windows subsystem, a double-clicked Kriko shortcut opened a
    terminal titled "Kriko" beside the app (seen on the 1.0.0 MSI)."""
    attribute = re.compile(
        r'#!\[cfg_attr\(\s*not\(debug_assertions\)\s*,\s*windows_subsystem\s*=\s*"windows"\s*\)\]'
    )
    assert attribute.search((CRATE / "src" / "main.rs").read_text(encoding="utf-8")), (
        'kriko-ui/src-tauri/src/main.rs must carry '
        '#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]'
    )
