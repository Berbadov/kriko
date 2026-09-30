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

import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packaging"))

import pytest  # noqa: E402

import render_icon  # noqa: E402


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
    assert render_icon.TARGET.read_bytes() == render_icon.smooth_png(
        shapes, units, render_icon.MASTER
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


def test_the_frontend_serves_the_same_mark():
    """`ui/public/mark.svg` is a published copy, not a second drawing.

    Vite bundles only what lives under `ui/`, so the frontend cannot reach the
    source file and needs its own. `render_icon.main()` writes both from one
    read; this is what fails when somebody edits the source and reruns nothing.
    """
    assert render_icon.WEB_TARGET.read_text(encoding="utf-8") == (
        render_icon.SOURCE.read_text(encoding="utf-8")
    )


def test_the_frontend_serves_the_large_mark_too():
    """The rail draws the 64x64 drawing, and `ui/public/mark-large.svg` is its copy.

    B161: "Fix the pixelated Kriko logo in the top left". The rail drew the 16x16
    grid at 28px, a 1.75 scale that no rendering mode makes crisp. It draws the
    drawing now, which has real diagonals and scales smoothly, and the frontend
    can only reach files under `ui/`, so the drawing is published there by the
    same script that renders every other size from it. This is what fails when
    somebody edits the large mark and reruns nothing.
    """
    assert render_icon.WEB_LARGE_TARGET.read_text(encoding="utf-8") == (
        render_icon.LARGE_SOURCE.read_text(encoding="utf-8")
    )


def test_the_rail_draws_the_large_mark_smooth():
    """Pixel art at a fractional scale is what the reader called pixelated.

    Read off the two files that decide it: the component that names the image,
    and the stylesheet that says how it is scaled. Either half alone could be
    reverted quietly, and the source-reading tests above would still pass on a
    rail that looks exactly as it did.
    """
    root = Path(__file__).resolve().parents[3]
    rail = (root / "ui" / "src" / "lib" / "shell" / "Sidebar.svelte").read_text(encoding="utf-8")
    assert 'src="/static/mark-large.svg"' in rail, (
        "the rail no longer draws the large mark"
    )
    css = (root / "ui" / "src" / "styles" / "components.css").read_text(encoding="utf-8")
    at = css.index(".brand .mark {")
    # Comments stripped: the rule explains what it replaced, and naming the old
    # declaration in prose is not the declaration coming back.
    rule = re.sub(r"/\*.*?\*/", "", css[at : css.index("}", at)], flags=re.S)
    assert "pixelated" not in rule, (
        "the rail's mark is scaled as pixel art again; the drawing is a vector"
    )
    assert "width: 32px" in rule and "height: 32px" in rule, (
        "32px is half the drawing's 64-unit box; any other size is a fractional scale"
    )


def test_the_app_and_the_extension_show_the_same_letter():
    """The ratchet, and what it guards changed in 0.10.0.

    It used to compare two *drawings*: a rasterised glyph somebody made for
    the toolbar, against hand-placed rects on a 16x16 grid. Both were reduced
    to one *role* per cell — ground, letter, joint — because byte equality
    across an antialiased fringe is impossible and would have been the wrong
    question anyway. That caught them diverging.

    The extension's icons are now rendered from the same grid
    (`render_icon.EXTENSION_ICONS`), so they cannot diverge — there is one
    drawing. What this catches instead is somebody editing the mark and
    committing it without re-running the render, which is the same failure
    arriving through the other door, and the only one still open.

    The role reduction stays rather than a byte comparison, because it is the
    assertion worth making out loud: whatever the renderer does, the thing in
    the toolbar is the same *letter* as the thing in the taskbar.
    """
    assert render_icon.roles_from_svg(
        render_icon.SOURCE.read_text(encoding="utf-8")
    ) == render_icon.roles_from_png(render_icon.EXTENSION_ICON.read_bytes(), 16)


@pytest.mark.parametrize("size", sorted(render_icon.EXTENSION_ICONS))
def test_every_size_the_manifest_ships_is_what_the_grid_renders(size: int):
    """All four, byte for byte — the 32px one is not a special case.

    Chrome picks a size by display density and by where it is drawing, so a
    reader on a high-DPI machine may never see the one size a spot check
    happened to cover.
    """
    _, pixels = render_icon.grid(
        render_icon.SOURCE.read_text(encoding="utf-8")
    )
    icon = render_icon.EXTENSION_DIR / f"icon-{size}.png"
    assert icon.read_bytes() == render_icon.png(
        pixels, render_icon.EXTENSION_ICONS[size]
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


def test_the_mark_is_painted_in_the_panel_theme_s_own_colours():
    """The three colours are palette, not decoration.

    Ground, letter and joint are `--n-2`, `--n-9` and `--accent` of the panel
    theme — the theme the app opens in, ported from the extension's live
    stylesheet. A mark using anything else would sit on the rail as a foreign
    object, which is exactly how the lemon read.
    """
    # Both marks. They are one design in two drawings, and a colour changed in
    # only one of them is the drift that having two files could otherwise
    # cost — the small tile and the app icon quietly stopping being the same
    # product.
    svg = "\n".join(
        one.read_text(encoding="utf-8").lower()
        for one in (render_icon.SOURCE, render_icon.LARGE_SOURCE)
    )
    theme = (
        Path(__file__).resolve().parents[3]
        / "ui/src/styles/themes/panel.css"
    ).read_text(encoding="utf-8").lower()

    for label, colour, token in (
        ("the ground", "#15171c", "--n-2"),
        ("the letter", "#e7e9ed", "--n-9"),
        ("the joint", "#e8c04b", "--accent"),
    ):
        assert svg.count(colour) >= 2, (
            f"{label} is {colour} in one mark and not the other — the tile and "
            f"the app icon have stopped being the same product"
        )
        assert f"{token}: {colour}" in theme, (
            f"{label} is {colour} in the mark but the panel theme's {token} "
            f"has moved — one of the two needs to follow the other"
        )


def test_the_master_is_not_somewhere_the_build_writes_over_it():
    """`tauri icon <master>` fills `tauri/src-tauri/icons/`, icon.png included.

    The master lived in that directory until 2026-09-21, which made it both
    the command's input and one of its outputs: every installer build
    re-encoded the committed file (20,697 bytes in, 18,403 out) and left the
    tree dirty with a PNG nobody had edited. `tauri/README.md` carried a line
    that restored it from git by hand afterwards, which is a person standing
    in for a path change -- and one the packaging script never ran at all.

    The next gate run would have failed `test_the_committed_icon_is_what_the_
    mark_renders_to`, so the cost of forgetting was a red suite on work that
    was correct. Checked here rather than trusted, because the build that
    overwrites it is hand-run on a different machine.
    """
    root = Path(__file__).resolve().parents[3]
    generated = root / "tauri" / "src-tauri" / "icons"
    assert generated not in render_icon.TARGET.parents, (
        f"{render_icon.TARGET.relative_to(root)} is inside the directory "
        f"`tauri icon` generates into, so the build overwrites the master it "
        f"was given. Keep the master outside it"
    )
    build = (root / "packaging" / "build_desktop.ps1").read_text(encoding="utf-8")
    where = render_icon.TARGET.relative_to(root).as_posix()
    assert where.rsplit("/", 1)[-1] in build, (
        f"packaging/build_desktop.ps1 does not name {where}, so the installer "
        f"is built from an icon this script never rendered"
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


def test_every_brand_asset_actually_parses():
    """The one thing a test that greps for strings can never tell you.

    All of the above read the file for colours, sizes and shapes, and every one
    of them passed on a mark that browsers refused to draw: the comment
    explaining which theme tokens it uses wrote them as `--n-2`, and two
    hyphens cannot appear inside an XML comment. The SVG was invalid, the rail
    showed a broken-image glyph, the icon renderer — which reads the file with
    a regular expression rather than a parser — saw nothing wrong, and the
    whole suite was green.

    So: parse them. It is the same lesson as `test_the_shell_is_valid_rust` and
    it arrived the same way, through a build somebody looked at.
    """
    import xml.etree.ElementTree as ElementTree

    root = Path(__file__).resolve().parents[3]
    assets = sorted(
        {render_icon.SOURCE, render_icon.WEB_TARGET}
        | set((root / "extension" / "assets").glob("*.svg"))
        | set((root / "ui" / "public").glob("*.svg"))
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
