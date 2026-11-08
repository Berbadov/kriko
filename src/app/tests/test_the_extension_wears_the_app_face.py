"""The extension's panel and options page use the app's face, shipped inside it.

Inter Tight is bundled as two variable files (Latin, and Latin Extended for the
Turkish letters), registered under Kriko's own family name, and named in the
manifest so a page can load them. Nothing is fetched: the files are the
extension's own, and the licence sits beside them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

EXT = Path(__file__).resolve().parents[3] / "extension"
FONTS = EXT / "assets" / "fonts"


def test_the_face_and_its_licence_are_bundled():
    assert (FONTS / "InterTight-latin.woff2").is_file()
    assert (FONTS / "InterTight-latin-ext.woff2").is_file()
    assert "SIL Open Font License" in (FONTS / "OFL-InterTight.txt").read_text(encoding="utf-8")


def test_no_other_face_is_left_behind():
    assert sorted(path.suffix for path in FONTS.iterdir() if path.suffix != ".txt") == [".woff2", ".woff2"]


def test_the_panel_registers_what_is_shipped():
    source = (EXT / "hover_lite" / "hover_lite.js").read_text(encoding="utf-8")
    for name in re.findall(r'"(InterTight-[a-z-]+\.woff2)"', source):
        assert (FONTS / name).is_file(), name
    assert "InterTight-latin.woff2" in source and "InterTight-latin-ext.woff2" in source


def test_the_page_can_load_the_files():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    resources = [r for block in manifest["web_accessible_resources"] for r in block["resources"]]
    assert "assets/fonts/*.woff2" in resources


def test_both_sheets_use_the_same_family_name():
    for sheet in (EXT / "hover_lite" / "hover_lite.css", EXT / "options" / "options.css"):
        text = sheet.read_text(encoding="utf-8")
        assert "Kriko Display" not in text and "Kriko Mono" not in text, sheet.name
        assert "Kriko Sans" in text, sheet.name


def _palette(block: str) -> dict[str, str]:
    return {
        name: value.lower()
        for name, value in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block)
    }


def test_the_panel_and_the_page_keep_one_palette_with_the_app():
    app = (EXT.parent / "kriko-ui" / "src" / "styles" / "tokens.css").read_text(encoding="utf-8")
    palettes = {
        "dark": _palette(app[: app.index("@media (prefers-color-scheme: light)")]),
        "light": _palette(app[app.index(":root[data-theme='light']") :]),
    }
    for sheet in (EXT / "hover_lite" / "hover_lite.css", EXT / "options" / "options.css"):
        text = sheet.read_text(encoding="utf-8").lower()
        # The ground, the ink, the one navy and the good-sign grey are the app's,
        # in both themes, so the panel is the app's face and not a second one.
        for theme, palette in palettes.items():
            for token in ("ground", "ink", "accent", "ok"):
                assert token in palette, f"the app has no {token} in its {theme} palette"
                colour = palette[token]
                assert colour in text, f"{sheet.name} lacks the app's {theme} {token} {colour}"
