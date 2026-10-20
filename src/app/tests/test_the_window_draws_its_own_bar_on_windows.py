"""The Windows window has no system title bar; the app draws its own.

A system bar is a strip of the system's colour above the page, and the page can
neither tint nor remove it. Windows therefore asks for no decorations and the
page draws minimise, maximise and close itself (`kriko-ui/src/ui/TitleBar.tsx`).
Two ways that goes wrong without a crate build to show it: the platform file
drifts from the base window (its array replaces the base one whole, so a size
changed in one place is silently the old size on Windows), and the page asks the
window for something the capability file never allowed (the buttons then do
nothing, with no error anywhere a reader can see).
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TAURI = ROOT / "kriko-ui" / "src-tauri"
BAR = ROOT / "kriko-ui" / "src" / "ui" / "TitleBar.tsx"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_windows_drops_the_system_bar_and_keeps_the_rest_of_the_window():
    base = _json(TAURI / "tauri.conf.json")["app"]["windows"]
    windows = _json(TAURI / "tauri.windows.conf.json")["app"]["windows"]
    assert len(base) == len(windows) == 1
    assert windows[0].pop("decorations") is False
    assert windows[0] == base[0], "the platform file replaces the window whole; keep it in step"


def test_the_system_bar_stays_everywhere_else():
    assert "decorations" not in _json(TAURI / "tauri.conf.json")["app"]["windows"][0]


def test_the_page_may_drive_the_window_it_draws_controls_for():
    allowed = {p for p in _json(TAURI / "capabilities" / "default.json")["permissions"] if isinstance(p, str)}
    for permission in (
        "core:window:allow-minimize",
        "core:window:allow-toggle-maximize",
        "core:window:allow-close",
        "core:window:allow-start-dragging",
    ):
        assert permission in allowed, permission


def test_the_bar_draws_nothing_where_the_system_still_draws_one():
    source = BAR.read_text(encoding="utf-8")
    assert "isDecorated()" in source and "if (!bare) return null" in source
