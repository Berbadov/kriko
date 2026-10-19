"""The installer, read as the text it is.

The installer is the one thing a reader runs that this suite cannot execute
(`packaging/smoke_installer.py` does, on a Windows build), so the properties
that matter are asserted on its source: `kriko-ui/src-tauri/tauri.conf.json`,
`tauri.bundle.conf.json` and the NSIS hooks in `windows/hooks.nsh`.

* **It is per-user.** No elevation prompt, nothing under Program Files, and no
  edit to the machine PATH.
* **It stops a running Kriko first, app before engine, as tree kills.** The
  engine maps its own image, so a live one fails the copy. Ending `kriko.exe`
  closes the engine's stdin, which is its designed way out; the second kill is
  the belt. `/T` because the frozen engine re-executes.
* **It carries every program the app starts**, beside `kriko.exe`: the engine
  and OpenSERP, plus OpenSERP's licence.
* **It makes the shortcuts the reader is promised**: Kriko, Kriko Console
  (`kriko-sidecar.exe --tui`), and a desktop one.
* **It upgrades in place**: the identifier is the product's identity, and a
  changed one makes every install a second product.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CRATE = ROOT / "kriko-ui" / "src-tauri"


def _config(name: str) -> dict:
    return json.loads((CRATE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def hooks() -> str:
    """The hooks with `;` comments stripped: a comment is not behaviour."""
    text = (CRATE / "windows" / "hooks.nsh").read_text(encoding="utf-8")
    return "\n".join(re.sub(r";.*$", "", line) for line in text.splitlines())


def _macro(hooks: str, name: str) -> str:
    found = re.search(rf"!macro {name}\b(.*?)!macroend", hooks, re.S)
    assert found, f"hooks.nsh has no {name} macro"
    return found.group(1)


def test_the_installer_is_per_user_and_touches_no_machine_state(hooks):
    nsis = _config("tauri.conf.json")["bundle"]["windows"]["nsis"]
    assert nsis["installMode"] == "currentUser"
    assert _config("tauri.conf.json")["bundle"]["targets"] == ["nsis"]
    assert "ProgramFiles" not in hooks and "PROGRAMFILES" not in hooks
    assert "EnVar" not in hooks and "Environment" not in hooks, (
        "a per-user install must not edit the PATH"
    )


def test_the_identity_that_upgrades_in_place_is_kept():
    assert _config("tauri.conf.json")["identifier"] == "com.kriko.app"
    assert _config("tauri.conf.json")["productName"] == "Kriko"


def test_the_installer_stops_the_app_before_the_engine_as_tree_kills(hooks):
    stop = _macro(hooks, "KrikoStopEverything")
    commands = re.findall(r"taskkill\.exe\"? (.*?)'", stop)
    assert [c.split("/IM ")[1] for c in commands] == [
        "kriko.exe",
        "kriko-sidecar.exe",
        "OpenSERP.exe",
    ], (
        "app first: its exit closes the engine's stdin, the engine's own "
        "designed exit and the only one that unwinds cleanly"
    )
    for command in commands:
        assert "/F" in command and "/T" in command, (
            "the frozen engine re-execs: without /T the child that holds the "
            "image mapped survives"
        )


def test_the_stop_runs_before_files_are_replaced_and_before_they_are_removed(hooks):
    for name in ("NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL"):
        assert "KrikoStopEverything" in _macro(hooks, name), (
            f"{name} does not stop Kriko, so a running engine fails the copy "
            "or leaves its folder behind"
        )


def test_the_engine_folder_is_replaced_whole_and_cleared_on_uninstall(hooks):
    """An overlay left `kriko-0.2.3.dist-info` beside 0.2.4 and the engine read
    its version from the old one; the same leftovers kept the folder from being
    removed. The folder is cleared after the stop, never before it."""
    clear = _macro(hooks, "KrikoClearEngineFolder")
    assert re.findall(r"RMDir /r (\S+)", clear) == ['"$INSTDIR\\_internal"'], (
        "only the engine's own folder may be removed recursively, and never "
        "the install folder itself"
    )
    for name in ("NSIS_HOOK_PREINSTALL", "NSIS_HOOK_PREUNINSTALL"):
        body = _macro(hooks, name)
        assert "KrikoClearEngineFolder" in body, name
        assert body.index("KrikoStopEverything") < body.index("KrikoClearEngineFolder"), (
            f"{name} clears the folder before it stops the engine that maps it"
        )
    assert "RMDir /r" not in hooks.replace(clear, ""), (
        "no other hook may remove anything recursively"
    )
    # The folder it clears is the one the bundle puts the engine in.
    bundle = _config("tauri.bundle.conf.json")["bundle"]
    assert "_internal" in bundle["resources"].values()


def test_the_names_it_stops_are_the_names_it_ships(hooks):
    bundle = _config("tauri.bundle.conf.json")["bundle"]
    shipped = {Path(name).name + ".exe" for name in bundle["externalBin"]}
    assert shipped == {"kriko-sidecar.exe", "OpenSERP.exe"}
    spec = (ROOT / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")
    assert 'name="kriko-sidecar"' in spec
    cargo = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
    assert re.search(r'^name = "kriko"', cargo, re.M)
    stopped = set(re.findall(r"/IM (\S+?)'", _macro(hooks, "KrikoStopEverything")))
    # OpenSERP is a shipped process the app starts, so an orphan of it would
    # hold its .exe against the next install like the other two.
    assert stopped == shipped | {"kriko.exe"}


def test_the_installer_carries_the_licence_of_what_it_ships():
    bundle = _config("tauri.bundle.conf.json")["bundle"]
    assert bundle["resources"] == {
        "third-party/OpenSERP-LICENSE.txt": "OpenSERP-LICENSE.txt",
        # the engine's folder, beside the program that needs it
        "binaries/_internal": "_internal",
    }
    assert (CRATE / "third-party" / "OpenSERP-LICENSE.txt").stat().st_size > 0


def test_the_bundled_programs_are_named_only_in_the_bundle_config():
    """`tauri_build` stops a plain `cargo check` or `tauri dev` over an external
    binary that is not there, and only a packaging run has the frozen engine.
    So the names live in the file `package.ps1` and `desktop.yml` pass, and
    never in the one the dev loop reads."""
    assert "externalBin" not in _config("tauri.conf.json")["bundle"]
    assert "resources" not in _config("tauri.conf.json")["bundle"]
    assert _config("tauri.bundle.conf.json")["bundle"]["externalBin"]


def test_the_installer_makes_the_console_a_thing_you_double_click(hooks):
    """One click, from the Start menu, into the operator console: the engine
    binary with `--tui`, wearing the app's icon. No second artifact."""
    made = _macro(hooks, "NSIS_HOOK_POSTINSTALL")
    shortcut = re.search(r'CreateShortcut "(.*?)" "(.*?)" "(.*?)" "(.*?)"', made)
    assert shortcut, "no console shortcut is made"
    link, target, arguments, icon = shortcut.groups()
    assert link == "$SMPROGRAMS\\Kriko Console.lnk"
    assert target == "$INSTDIR\\kriko-sidecar.exe"
    assert arguments == "--tui", (
        "without the flag the shortcut starts a headless engine and shows the "
        "reader a console that says nothing"
    )
    assert icon == "$INSTDIR\\kriko.exe"


def test_the_console_shortcut_goes_with_the_install(hooks):
    """A Start-menu entry that outlives its target is a click that does nothing."""
    removed = _macro(hooks, "NSIS_HOOK_POSTUNINSTALL")
    assert 'Delete "$SMPROGRAMS\\Kriko Console.lnk"' in removed


def test_the_app_has_a_start_menu_and_a_desktop_shortcut():
    """Tauri's NSIS template makes both, and its opt-outs are `startMenuFolder`
    and the installer's own checkbox. Nothing here turns them off; if a config
    key ever does, the promise in the README is broken."""
    nsis = _config("tauri.conf.json")["bundle"]["windows"]["nsis"]
    assert "startMenuFolder" not in nsis


def test_the_installer_uses_the_one_brand_icon():
    nsis = _config("tauri.conf.json")["bundle"]["windows"]["nsis"]
    assert nsis["installerIcon"] == "icons/icon.ico"
    assert "icons/icon.ico" in _config("tauri.conf.json")["bundle"]["icon"]


def test_the_hooks_are_the_file_tauri_is_told_to_read():
    nsis = _config("tauri.conf.json")["bundle"]["windows"]["nsis"]
    assert nsis["installerHooks"] == "windows/hooks.nsh"
    assert (CRATE / nsis["installerHooks"]).is_file()


def test_the_desktop_engine_is_a_folder_so_it_starts_without_unpacking_itself():
    """A one-file engine unpacks all of itself into temp on every start, which
    took 10 to 13 s on Windows before it could say a word, and that wait was the
    blank window. The desktop app's engine is a program with a `_internal`
    folder beside it, in every recipe that builds the installer."""
    spec = (ROOT / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")
    assert 'KRIKO_FREEZE") == "folder"' in spec and "COLLECT(" in spec
    resources = _config("tauri.bundle.conf.json")["bundle"]["resources"]
    assert resources["binaries/_internal"] == "_internal"
    for recipe in (CRATE.parent / "package.ps1", ROOT / ".github" / "workflows" / "desktop.yml"):
        text = recipe.read_text(encoding="utf-8")
        assert re.search(r"KRIKO_FREEZE\W+\s*=?\s*\"?folder", text), f"{recipe.name} freezes one file"
        assert "kriko-engine" in text and "_internal" in text, recipe.name
