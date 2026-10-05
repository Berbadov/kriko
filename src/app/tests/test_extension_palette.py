"""The extension's two sheets carry one palette.

The panel (`hover_lite.css`) and the settings page (`options.css`) used to
receive their colours from the Svelte app's theme through a generator. The
Svelte app is gone, so the panel's block is the palette now, and the one
thing left to keep is that the two sheets do not drift apart.
"""

import re
from pathlib import Path

EXTENSION = Path(__file__).resolve().parents[3] / "extension"
_BLOCK = re.compile(r"/\* BEGIN palette.*?\*/(.*?)/\* END palette \*/", re.S)


def _palette(relative: str) -> str:
    text = (EXTENSION / relative).read_text(encoding="utf-8")
    found = _BLOCK.search(text)
    assert found, f"{relative} has no palette block"
    return found.group(1)


def test_the_panel_and_the_settings_page_share_one_palette():
    assert _palette("hover_lite/hover_lite.css") == _palette("options/options.css")
