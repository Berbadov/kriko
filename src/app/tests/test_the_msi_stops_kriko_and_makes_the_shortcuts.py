"""The installer, read as the XML it is.

The MSI is the one thing a reader runs that this suite cannot execute, so the
properties that matter are asserted on `kriko-gpui/wix/main.wxs`:

* **It is per-user.** No elevation prompt, nothing under Program Files, and no
  edit to the machine PATH.
* **It stops a running Kriko first, app before engine, as tree kills.** The
  sidecar maps its own image, so a live one fails the copy. Ending `kriko.exe`
  closes the sidecar's stdin, which is the engine's designed way out; the
  second kill is the belt. `/T` because the one-file bundle re-executes.
* **It carries both programs and the shortcuts the reader is promised**:
  Kriko, Kriko Console (`kriko-sidecar.exe --tui`), and a desktop one.
* **It upgrades in place** and keeps the product's `UpgradeCode`, or every
  install becomes a second product.

The old shell's NSIS tests held the same stop-order and console-shortcut
properties; this is where they live now.
"""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WXS = ROOT / "kriko-gpui" / "wix" / "main.wxs"
NS = {"w": "http://schemas.microsoft.com/wix/2006/wi"}


@pytest.fixture(scope="module")
def wix() -> ET.Element:
    return ET.parse(WXS).getroot()


def _actions(wix: ET.Element) -> dict[str, ET.Element]:
    return {a.get("Id"): a for a in wix.iter("{%s}CustomAction" % NS["w"])}


def test_the_msi_is_per_user_and_touches_no_machine_state(wix):
    package = next(wix.iter("{%s}Package" % NS["w"]))
    assert package.get("InstallScope") == "perUser"
    text = WXS.read_text(encoding="utf-8")
    assert "LocalAppDataFolder" in text
    assert "ProgramFiles" not in re.sub(r"<!--.*?-->", "", text, flags=re.S)
    assert not list(wix.iter("{%s}Environment" % NS["w"])), (
        "a per-user install must not edit the PATH"
    )


def test_the_upgrade_code_and_major_upgrade_are_kept(wix):
    product = next(wix.iter("{%s}Product" % NS["w"]))
    cargo = tomllib.loads((ROOT / "kriko-gpui" / "Cargo.toml").read_text(encoding="utf-8"))
    assert product.get("UpgradeCode").upper() == (
        cargo["package"]["metadata"]["wix"]["upgrade-guid"].upper()
    )
    assert product.get("UpgradeCode") == "D4A3E5B4-6C7D-4C42-8B0D-0FE43E4E5F21"
    assert list(wix.iter("{%s}MajorUpgrade" % NS["w"]))


def test_the_installer_stops_the_app_before_the_engine_as_tree_kills(wix):
    actions = _actions(wix)
    kriko = actions["SetStopKriko"].get("Value")
    engine = actions["SetStopEngine"].get("Value")
    assert "/IM kriko.exe" in kriko and "/IM kriko-sidecar.exe" in engine
    for command in (kriko, engine):
        assert "/F" in command and "/T" in command, (
            "PyInstaller onefile re-execs: without /T the child that holds "
            "the image mapped survives"
        )
    order = [c.get("Action") for c in wix.iter("{%s}Custom" % NS["w"])]
    assert order.index("StopKriko") < order.index("StopEngine"), (
        "app first: its exit closes the sidecar's stdin, the engine's own "
        "designed exit and the only one that unwinds cleanly"
    )
    for name in ("StopKriko", "StopEngine"):
        assert actions[name].get("Return") == "ignore", (
            "'no such process' is the expected answer and must not fail the install"
        )


def test_the_stop_runs_before_the_old_version_is_removed(wix):
    first = next(
        c for c in wix.iter("{%s}Custom" % NS["w"]) if c.get("Action") == "SetStopKriko"
    )
    assert first.get("Before") == "RemoveExistingProducts"


def test_the_names_it_stops_are_the_names_it_ships(wix):
    cargo = tomllib.loads((ROOT / "kriko-gpui" / "Cargo.toml").read_text(encoding="utf-8"))
    app = cargo["bin"][0]["name"] + ".exe"
    spec = (ROOT / "packaging" / "kriko-sidecar.spec").read_text(encoding="utf-8")
    assert 'name="kriko-sidecar"' in spec
    files = {f.get("Name") for f in wix.iter("{%s}File" % NS["w"])}
    assert files == {app, "kriko-sidecar.exe"}
    text = "".join(a.get("Value") or "" for a in _actions(wix).values())
    assert f"/IM {app}" in text and "/IM kriko-sidecar.exe" in text


def test_the_installer_makes_the_console_a_thing_you_double_click(wix):
    """One click, from the Start menu, into the operator console: the engine
    binary with `--tui`, wearing the app's icon. No second artifact."""
    shortcuts = {s.get("Id"): s for s in wix.iter("{%s}Shortcut" % NS["w"])}
    console = shortcuts["StartMenuConsole"]
    assert console.get("Name") == "Kriko Console"
    assert console.get("Target") == "[APPLICATIONFOLDER]kriko-sidecar.exe"
    assert console.get("Arguments") == "--tui", (
        "without the flag the shortcut starts a headless engine and shows the "
        "reader a console that says nothing"
    )
    assert console.get("Icon")
    assert console.get("Directory") == "ProgramMenuFolder"


def test_the_app_has_a_start_menu_and_a_desktop_shortcut(wix):
    shortcuts = {s.get("Id"): s for s in wix.iter("{%s}Shortcut" % NS["w"])}
    assert shortcuts["StartMenuKriko"].get("Name") == "Kriko"
    assert shortcuts["DesktopKriko"].get("Directory") == "DesktopFolder"
    for key in ("StartMenuKriko", "DesktopKriko"):
        assert shortcuts[key].get("Target") == "[APPLICATIONFOLDER]kriko.exe"


def test_every_shortcut_goes_with_the_install(wix):
    """A Start-menu entry that outlives its target is a click that does
    nothing: each shortcut lives in a component that Windows Installer removes
    with the feature, and every component is in the feature."""
    refs = {c.get("Id") for c in wix.iter("{%s}ComponentRef" % NS["w"])}
    comps = {c.get("Id") for c in wix.iter("{%s}Component" % NS["w"])}
    assert comps == refs
    for comp in wix.iter("{%s}Component" % NS["w"]):
        if list(comp.iter("{%s}Shortcut" % NS["w"])):
            assert list(comp.iter("{%s}RegistryValue" % NS["w"])), (
                "a user-profile shortcut needs an HKCU key path (ICE38)"
            )


def test_the_installer_uses_the_one_brand_icon():
    text = WXS.read_text(encoding="utf-8")
    assert "assets/kriko.ico" in text
