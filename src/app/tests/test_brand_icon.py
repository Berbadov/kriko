"""The app icon is derived from the brand mark, not maintained beside it.

Two files drawing the same lemon is how they end up drawing different lemons.
`packaging/render_icon.py` is the derivation; these tests are what stop the
committed PNG from drifting away from the SVG it claims to be.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))

import render_icon  # noqa: E402


def test_the_committed_icon_is_what_the_mark_renders_to():
    """Edit the SVG without re-rendering and this fails, which is the point."""
    side, pixels = render_icon.grid(
        render_icon.SOURCE.read_text(encoding="utf-8")
    )
    assert render_icon.TARGET.read_bytes() == render_icon.png(
        pixels, render_icon.SCALE
    )


def test_the_master_is_large_enough_for_every_icon_tauri_derives():
    """`tauri icon` derives up to 1024; a smaller master upscales and blurs."""
    header = render_icon.TARGET.read_bytes()[16:24]
    width, height = struct.unpack(">II", header)
    assert width == height == 1024


def test_the_scale_keeps_the_grid_whole():
    """Nearest-neighbour by an exact integer factor, or the pixel art smears."""
    side, _ = render_icon.grid(render_icon.SOURCE.read_text(encoding="utf-8"))
    assert render_icon.SCALE * side == 1024
    assert 1024 % side == 0
