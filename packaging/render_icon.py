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


def main() -> None:
    side, pixels = grid(SOURCE.read_text(encoding="utf-8"))
    TARGET.write_bytes(png(pixels, SCALE))
    print(f"{SOURCE.name} ({side}x{side}) -> {TARGET} ({side * SCALE}px)")


if __name__ == "__main__":
    main()
