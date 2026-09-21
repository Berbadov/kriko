"""Render the pixel-art brand mark to the PNG Tauri derives every icon from.

`extension/assets/logo-mark.svg` is a 16x16 grid of `<rect>` elements — pixel
art that happens to be written as SVG. That makes it the right source for an
app icon and the wrong thing to hand a rasteriser: any antialiasing smears the
grid, and scaling the extension's 128px PNG loses the edges the mark is made of.

So this scales the grid itself, nearest-neighbour, by an exact integer factor.
64x gives the 1024px master `tauri icon` wants; every derived size is a clean
division of it.

A script rather than a committed blob because the mark will change, and
"re-run this" beats "remember how the last one was made". No third-party
imports: adding Pillow to the build for one 40-line raster would be a strange
dependency to explain.

    python packaging/render_icon.py

Writes `tauri/src-tauri/icons/icon.png`, the 1024px master every other size is
derived from, and `icon.ico`, which is the one derived file that has to exist
*before* the shell will compile on Windows rather than when it is bundled. The
packaging step's `tauri icon` writes the remaining sizes from the same master.
"""

import re
import struct
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "extension" / "assets" / "logo-mark.svg"
TARGET = REPO / "tauri" / "src-tauri" / "icons" / "icon.png"
#: The same mark, served to the frontend as the rail brand and the favicon.
#: A copy rather than an import because `ui/` may not reach outside itself —
#: Vite only bundles what lives under `ui/` — and a copy that is produced by
#: the same script that produces the icon cannot drift from it. `test_brand_
#: icon.py` fails if it ever does.
WEB_TARGET = REPO / "ui" / "public" / "mark.svg"

#: 16 * 64. Tauri's largest derived icon is 1024, and an exact multiple keeps
#: every smaller one a whole number of source pixels.
SCALE = 64

#: The Windows icon, and the one file `cargo check` cannot proceed without on
#: a Windows host — `tauri-build` generates a Win32 resource from it before
#: rustc reads a line, so its absence is not a missing *icon*, it is the whole
#: shell failing to compile.
#:
#: Every other derived size comes from `tauri icon`, which `desktop.yml` runs
#: and which needs the Tauri CLI and a network to install it. `tools/gate.sh`
#: has neither on purpose. That left the tauri leg unrunnable on exactly the
#: machine that builds the installers — and an unrunnable cargo check is how a
#: `main.rs` that could not be parsed shipped in B83. So this one file is
#: derived here instead, by the renderer that already exists: an ICO is a
#: 6-byte directory, one 16-byte entry per image, and then PNGs, which is a
#: container, not a rasteriser, and stays inside this file's no-dependencies
#: rule. `tauri icon` still overwrites it at bundle time; the two agree
#: because both start from `icon.png`'s source.
ICO_TARGET = REPO / "tauri" / "src-tauri" / "icons" / "icon.ico"
#: Scale per stored image. Windows picks the nearest at display time, so the
#: set is the conventional one — and every entry is a whole multiple of the
#: 16-cell grid, for the same reason `EXTENSION_ICONS` is.
ICO_SIZES = (1, 2, 3, 4, 8, 16)

RECT = re.compile(
    r'<rect\s+x="(\d+)"\s+y="(\d+)"\s+width="(\d+)"\s+height="(\d+)"\s+fill="#([0-9A-Fa-f]{6})"'
)


def grid(svg: str) -> tuple[int, list[list[tuple[int, int, int, int]]]]:
    """The mark as rows of RGBA pixels, painted in document order.

    Later rects overpaint earlier ones — the source relies on it for the
    highlight strokes — so this is a paint, not a lookup.
    """
    side = int(re.search(r'viewBox="0 0 (\d+) \d+"', svg).group(1))
    pixels = [[(0, 0, 0, 0)] * side for _ in range(side)]
    for x, y, w, h, colour in RECT.findall(svg):
        rgb = tuple(int(colour[i : i + 2], 16) for i in (0, 2, 4))
        for row in range(int(y), int(y) + int(h)):
            for col in range(int(x), int(x) + int(w)):
                if 0 <= row < side and 0 <= col < side:
                    pixels[row][col] = (*rgb, 255)
    return side, pixels


def png(pixels: list[list[tuple[int, int, int, int]]], scale: int) -> bytes:
    side = len(pixels)
    size = side * scale
    raw = bytearray()
    for row in pixels:
        line = bytearray()
        for pixel in row:
            line += bytes(pixel) * scale
        # Filter byte 0 (None) per scanline — the image is flat colour, so a
        # cleverer filter would buy nothing but a harder file to verify.
        raw += (b"\x00" + line) * scale

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )



def ico(pixels: list[list[tuple[int, int, int, int]]], scales: tuple[int, ...]) -> bytes:
    """The same grid as a Windows ICO holding one PNG per scale.

    PNG-in-ICO rather than the older BMP-with-AND-mask form: Windows has read
    it since Vista, it is what `tauri icon` writes, and it means the images
    here are byte-identical to the ones `png()` produces everywhere else —
    there is one renderer, not a second one for this format.
    """
    images = [png(pixels, scale) for scale in scales]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    directory, body = b"", b""
    for scale, image in zip(scales, images):
        side = len(pixels) * scale
        directory += struct.pack(
            "<BBBBHHII",
            # 0 means 256 — the field is one byte, so the largest size a
            # directory entry can name outright is 255.
            side if side < 256 else 0,
            side if side < 256 else 0,
            0,  # not a palette
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel — RGBA, as `png()` writes
            len(image),
            offset,
        )
        body += image
        offset += len(image)
    return header + directory + body


#: The extension's toolbar icons, and the scale each is rendered at. Every
#: size Chrome asks for is a whole multiple of the 16-cell grid, which is why
#: this list is these four numbers and not any four numbers.
#:
#: **These were hand-drawn until 0.10.0, and that is the thing that changed.**
#: A rasterised glyph beside a grid of rects is two people drawing one letter,
#: and `test_the_app_and_the_extension_show_the_same_letter` existed to catch
#: them diverging. Deriving both from one source does not catch divergence —
#: it makes it unrepresentable, which is the better half of that bargain. What
#: the test now guards is that somebody re-ran this after editing the mark.
EXTENSION_ICONS = {16: 1, 32: 2, 48: 3, 128: 8}
EXTENSION_DIR = REPO / "extension" / "assets" / "icons"
#: The one the role check reads back. 32 because that is the size a toolbar
#: actually shows, so it is the rendering a mistake would be visible in.
EXTENSION_ICON = EXTENSION_DIR / "icon-32.png"


def decode(data: bytes) -> tuple[int, int, bytes]:
    """A minimal 8-bit RGBA PNG reader — enough for our own icons.

    Written out rather than imported for the reason the writer above was: one
    check does not justify putting Pillow in the build. Handles the five PNG
    scanline filters and nothing else, because nothing else is what we produce.
    """
    position, idat = 8, b""
    width = height = 0
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        tag = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + length]
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", payload[:10])
            if (depth, colour) != (8, 6):
                raise ValueError(f"not 8-bit RGBA: depth {depth}, colour {colour}")
        elif tag == b"IDAT":
            idat += payload
        position += 12 + length

    raw = zlib.decompress(idat)
    stride, out, previous, at = width * 4, bytearray(), bytearray(width * 4), 0
    for _ in range(height):
        filter_type, at = raw[at], at + 1
        line = bytearray(raw[at : at + stride])
        at += stride
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = previous[i]
            up_left = previous[i - 4] if i >= 4 else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                estimate = left + up - up_left
                deltas = (
                    (abs(estimate - left), left),
                    (abs(estimate - up), up),
                    (abs(estimate - up_left), up_left),
                )
                line[i] = (line[i] + min(deltas)[1]) & 0xFF
        out += line
        previous = line
    return width, height, bytes(out)


#: What each pixel of the mark *is*, independent of the exact hex either file
#: happens to use. Comparing roles rather than colours is what lets the two
#: renderings differ in antialiasing — which they must, one being a rasterised
#: glyph — while still being checkably the same letter.
GROUND, LETTER, JOINT = ".", "W", "A"


def role(red: int, green: int, blue: int) -> str:
    if red > 180 and green > 150 and blue < 140:
        return JOINT
    return LETTER if (red + green + blue) / 3 > 150 else GROUND


def roles_from_svg(svg: str) -> list[str]:
    """The mark as one role per grid cell, row-major."""
    _, pixels = grid(svg)
    return [role(*pixel[:3]) for row in pixels for pixel in row]


def roles_from_png(data: bytes, side: int) -> list[str]:
    """The same, read back off a rendered icon and reduced to `side` cells.

    Each cell is a block of the source. A block counts as part of the letter
    when at least half of it is: at this size the glyph's antialiased fringe is
    a minority of every block it touches, so the majority is the stroke.
    """
    width, height, pixels = decode(data)
    if width % side or height % side:
        raise ValueError(f"{width}x{height} does not divide into {side}")
    block = width // side
    out = []
    for cell_y in range(side):
        for cell_x in range(side):
            seen = {JOINT: 0, LETTER: 0}
            for y in range(cell_y * block, (cell_y + 1) * block):
                for x in range(cell_x * block, (cell_x + 1) * block):
                    offset = (y * width + x) * 4
                    found = role(*pixels[offset : offset + 3])
                    if found in seen:
                        seen[found] += 1
            half = block * block / 2
            out.append(
                JOINT if seen[JOINT] >= half
                else LETTER if seen[LETTER] >= half
                else GROUND
            )
    return out


def main() -> None:
    svg = SOURCE.read_text(encoding="utf-8")
    side, pixels = grid(svg)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(png(pixels, SCALE))
    ICO_TARGET.write_bytes(ico(pixels, ICO_SIZES))
    WEB_TARGET.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""` for the reason `tauri.conf.json` is written as bytes: the
    # default translates every `\n` to `\r\n` on Windows, so running the render
    # there rewrote all 37 lines of a file whose content had not changed. A
    # no-op diff that appears whenever one particular host runs a tool is worse
    # than noise — it teaches the reader of the diff to skip the file, and this
    # is the file that is supposed to fail loudly when the mark drifts.
    WEB_TARGET.write_text(svg, encoding="utf-8", newline="")
    print(f"{SOURCE.name} ({side}x{side}) -> {TARGET} ({side * SCALE}px)")
    print(f"{SOURCE.name} -> {ICO_TARGET} "
          f"({', '.join(f'{side * one}px' for one in ICO_SIZES)})")
    print(f"{SOURCE.name} -> {WEB_TARGET}")
    EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    for size, scale in sorted(EXTENSION_ICONS.items()):
        if side * scale != size:
            raise ValueError(f"{size}px is not {side} cells at {scale}x")
        (EXTENSION_DIR / f"icon-{size}.png").write_bytes(png(pixels, scale))
    print(f"{SOURCE.name} -> {EXTENSION_DIR}/icon-"
          f"{{{','.join(str(one) for one in sorted(EXTENSION_ICONS))}}}.png")


if __name__ == "__main__":
    main()
