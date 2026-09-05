"""The app icon is derived from the brand mark, not maintained beside it.

Two files drawing the same letter is how they end up drawing different letters.
`packaging/render_icon.py` is the derivation; these tests are what stop the
committed PNG, the frontend's copy, and the extension's toolbar icon from
drifting apart.

The mark is a K on the extension's near-black ground, with the amber joint at
its spine — and it is a K in three places at once: the browser toolbar the
reader met the product in, the taskbar tile the installer creates, and the rail
at the top-left of every screen. Until 0.3.1 the last two were a lemon, left
over from a design that was never the product. That is the failure with the
longest half-life here: nobody files a bug about an icon, they just stop
recognising the thing.
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


def test_the_frontend_serves_the_same_mark():
    """`ui/public/mark.svg` is a published copy, not a second drawing.

    Vite bundles only what lives under `ui/`, so the frontend cannot reach the
    source file and needs its own. `render_icon.main()` writes both from one
    read; this is what fails when somebody edits the source and reruns nothing.
    """
    assert render_icon.WEB_TARGET.read_text(encoding="utf-8") == (
        render_icon.SOURCE.read_text(encoding="utf-8")
    )


def test_the_app_and_the_extension_show_the_same_letter():
    """The ratchet. One mark, two renderings, checked as the same letter.

    Byte equality is impossible and would be the wrong test: the extension's
    icon is a rasterised glyph with an antialiased fringe, and the mark is
    hand-placed rects on a 16x16 grid. So both are reduced to one *role* per
    cell — ground, letter, joint — which is a claim about the shape rather than
    about anybody's hex values.

    It fails in either direction, which is what makes it worth having: restyle
    the extension's icon and the app's mark is now wrong; redraw the mark and
    the extension's is. Neither is a change somebody should be able to land
    without noticing the other half.
    """
    assert render_icon.roles_from_svg(
        render_icon.SOURCE.read_text(encoding="utf-8")
    ) == render_icon.roles_from_png(render_icon.EXTENSION_ICON.read_bytes(), 16)


def test_the_mark_is_painted_in_the_panel_theme_s_own_colours():
    """The three colours are palette, not decoration.

    Ground, letter and joint are `--n-2`, `--n-9` and `--accent` of the panel
    theme — the theme the app opens in, ported from the extension's live
    stylesheet. A mark using anything else would sit on the rail as a foreign
    object, which is exactly how the lemon read.
    """
    svg = render_icon.SOURCE.read_text(encoding="utf-8").lower()
    theme = (
        Path(__file__).resolve().parents[3]
        / "ui/src/styles/themes/panel.css"
    ).read_text(encoding="utf-8").lower()

    for label, colour, token in (
        ("the ground", "#15171c", "--n-2"),
        ("the letter", "#e7e9ed", "--n-9"),
        ("the joint", "#e8c04b", "--accent"),
    ):
        assert colour in svg, f"{label} is no longer {colour} in the mark"
        assert f"{token}: {colour}" in theme, (
            f"{label} is {colour} in the mark but the panel theme's {token} "
            f"has moved — one of the two needs to follow the other"
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
