"""The app icon is derived from the brand mark, not maintained beside it.

Two files drawing the same letter is how they end up drawing different letters.
`packaging/render_icon.py` is the derivation; these tests are what stop the
committed PNG and the extension's toolbar icon from
drifting apart.

The mark is a K on the extension's near-black ground, with the amber joint at
its spine — and it is a K in three places at once: the browser toolbar the
reader met the product in, the taskbar tile the installer creates, and the rail
at the top-left of every screen. Until 0.3.1 the last two were a lemon, left
over from a design that was never the product. That is the failure with the
longest half-life here: nobody files a bug about an icon, they just stop
recognising the thing.
"""

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))

import pytest  # noqa: E402

import render_icon  # noqa: E402


def _pixels(blob: bytes):
    """An image's size and pixels, whatever its compression produced.

    The assertions here used to compare *bytes*, which is a comparison of PNG
    streams rather than of pictures: two encoders that emit different (equally
    valid) deflate output for the same image fail it. That is exactly what
    happened — `pytest` on the machine this was written on reported three
    failures whose images decode to identical pixels, so a red meant "your zlib
    changed", which is the sort of red people learn to ignore. `render_icon`
    already carries the decoder (written for this purpose, and without pulling
    Pillow into the build), so the comparison is what the docstrings claim.
    """
    width, height, pixels = render_icon.decode(blob)
    return width, height, pixels


def test_the_committed_icon_is_what_the_mark_renders_to():
    """Edit the SVG without re-rendering and this fails, which is the point.

    Against the *large* mark since 0.10.1. The master used to be the 16-cell
    grid scaled 64x, which made the app icon eight hard blocks with a 64px
    cell — the reader's "pixelated and very ugly". The grid still renders
    everything at 128px and below, where it is the right answer.
    """
    units, shapes = render_icon.outlines(
        render_icon.LARGE_SOURCE.read_text(encoding="utf-8")
    )
    committed = _pixels(render_icon.TARGET.read_bytes())
    rendered = _pixels(render_icon.smooth_png(shapes, units, render_icon.MASTER))
    assert committed == rendered, (
        f"{render_icon.TARGET.name} is not what the mark renders to; "
        "run `python packaging/render_icon.py`"
    )


def test_the_app_icon_is_actually_antialiased():
    """The regression this pair of files exists to prevent.

    A mark rendered from the grid has exactly three colours at any size, and
    that is what made the icon look like a screenshot of itself. A real
    rasterisation of the same letter carries a fringe along every diagonal, so
    counting distinct colours tells the two apart without anybody eyeballing a
    PNG — which is the only reason this defect survived as long as it did.
    """
    width, height, pixels = render_icon.decode(render_icon.TARGET.read_bytes())
    seen = {pixels[i : i + 3] for i in range(0, len(pixels), 4)}
    assert len(seen) > 32, (
        f"the master has only {len(seen)} distinct colours, so its diagonals "
        "are steps rather than edges — it is being rendered from the grid"
    )
    assert width == height == render_icon.MASTER


@pytest.mark.parametrize("size", render_icon.EXTENSION_ICONS)
def test_the_toolbar_shows_the_desktop_app_s_own_icon(size: int):
    """All four sizes, byte for byte, are the desktop icon's own images.

    Since 1.0.1 there is one mark: the toolbar, the exe, the taskbar and the
    installer all show the white K on the brand plate from `kriko.ico`. A
    toolbar icon that is not those bytes is a second drawing of the letter,
    which is how the extension kept the old mark after the app changed.
    Chrome picks a size by display density, so every size is checked.
    """
    images = render_icon.ico_images(render_icon.DESKTOP_ICO.read_bytes())
    icon = render_icon.EXTENSION_DIR / f"icon-{size}.png"
    assert icon.read_bytes() == images[size], (
        f"{icon.name} is not the desktop icon's {size}px image; "
        "run `python packaging/render_icon.py`"
    )


@pytest.mark.parametrize("size", render_icon.EXTENSION_ICONS)
def test_offline_toolbar_icon_keeps_the_mark_but_mutes_it(size: int):
    side, pixels = render_icon.grid(
        render_icon.SOURCE.read_text(encoding="utf-8")
    )
    icon = render_icon.EXTENSION_DIR / f"icon-offline-{size}.png"
    assert _pixels(icon.read_bytes()) == _pixels(
        render_icon.png(render_icon.offline_grid(pixels), size // side)
    ), f"{icon.name} is not the muted mark; run `python packaging/render_icon.py`"
    # And it is a *muted* variant rather than a copy: a "offline" icon that is
    # the online one is a state the reader cannot see.
    assert _pixels(icon.read_bytes()) != _pixels(
        (render_icon.EXTENSION_DIR / f"icon-{size}.png").read_bytes()
    )


def test_the_manifest_asks_for_no_size_the_render_does_not_make():
    """The list of sizes lives in two files and they have to agree.

    `manifest.json` names the icons Chrome loads; `EXTENSION_ICONS` names the
    ones the render writes. A size in the manifest and not in the render is a
    broken image in a toolbar, which is the kind of thing nobody files.
    """
    manifest = json.loads(
        (Path(__file__).resolve().parents[3] / "extension/manifest.json")
        .read_text(encoding="utf-8")
    )
    asked = {int(one) for one in manifest["icons"]}
    asked |= {int(one) for one in manifest["action"]["default_icon"]}
    assert asked <= set(render_icon.EXTENSION_ICONS), (
        f"the manifest asks for {sorted(asked - set(render_icon.EXTENSION_ICONS))} "
        "and render_icon.py does not render it"
    )


def test_the_desktop_icon_is_a_whole_ico():
    """`kriko-ui/src-tauri/icons/icon.ico` is the one file the exe and the installer read.

    Tauri embeds it in kriko.exe (the taskbar, the tray) and the installer hands
    it to the shortcuts and Add/Remove Programs. It is a hand-drawn tile, not
    rendered from the mark, so nothing derives it and nothing would notice it
    going missing or turning into a one-size file -- both of which draw a
    blurred or blank icon on a machine nobody tests.
    """
    import json

    root = Path(__file__).resolve().parents[3]
    ico = root / "kriko-ui" / "src-tauri" / "icons" / "icon.ico"
    data = ico.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "not an ICO"
    sides = set()
    for one in range(count):
        side, _, _, _, _, _, length, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * one : 22 + 16 * one]
        )
        assert data[offset : offset + 4] == b"\x89PNG", "entry is not a PNG"
        assert offset + length <= len(data)
        sides.add(side or 256)
    assert {16, 32, 48, 256} <= sides, f"sizes {sorted(sides)} leave a size to scale"
    config = json.loads(
        (root / "kriko-ui" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    assert "icons/icon.ico" in config["bundle"]["icon"], (
        "tauri.conf.json does not bundle icons/icon.ico, so the installed app "
        "is not wearing the icon this test checks"
    )


def test_the_master_is_large_enough():
    """A smaller master upscales and blurs whatever is derived from it."""
    header = render_icon.TARGET.read_bytes()[16:24]
    width, height = struct.unpack(">II", header)
    assert width == height == 1024


def test_the_scale_keeps_the_grid_whole():
    """Nearest-neighbour by an exact integer factor, or the pixel art smears."""
    side, _ = render_icon.grid(render_icon.SOURCE.read_text(encoding="utf-8"))
    assert render_icon.SCALE * side == 1024
    assert 1024 % side == 0


def test_every_brand_asset_actually_parses():
    """The one thing a test that greps for strings can never tell you.

    Parse every mark and logo shipped by the extension. Text checks are not
    enough to prove an SVG is valid XML.
    """
    import xml.etree.ElementTree as ElementTree

    root = Path(__file__).resolve().parents[3]
    assets = sorted(
        {render_icon.SOURCE}
        | set((root / "extension" / "assets").glob("*.svg"))
    )
    assert assets, "no brand SVGs found; the glob is wrong"
    for asset in assets:
        try:
            ElementTree.parse(asset)
        except ElementTree.ParseError as why:
            raise AssertionError(
                f"{asset.relative_to(root)} is not well-formed XML, so no "
                f"browser will draw it: {why}"
            ) from why
