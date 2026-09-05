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

Writes `tauri/src-tauri/icons/icon.png`. CI's `tauri icon` step does the rest.
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



#: The extension's toolbar icon — the same mark, rendered by whoever drew it,
#: at 32px. Not an input to the render: an *invariant* the render is checked
#: against, so the tile in a browser toolbar and the tile in a taskbar cannot
#: quietly become two different letters. See `src/app/tests/test_brand_icon.py`.
EXTENSION_ICON = REPO / "extension" / "assets" / "icons" / "icon-32.png"


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
    TARGET.write_bytes(png(pixels, SCALE))
    WEB_TARGET.parent.mkdir(parents=True, exist_ok=True)
    WEB_TARGET.write_text(svg, encoding="utf-8")
    print(f"{SOURCE.name} ({side}x{side}) -> {TARGET} ({side * SCALE}px)")
    print(f"{SOURCE.name} -> {WEB_TARGET}")


if __name__ == "__main__":
    main()
