"""Render the brand mark to the 1024px master PNG, the frontend copies and the
extension icons.

There are two marks and one design, and the split is the point.

`extension/assets/logo-mark.svg` is a 16x16 grid of `<rect>` elements — pixel
art that happens to be written as SVG. At the sizes it was drawn for it is the
right answer and antialiasing is the wrong one: a hairline K closes into a
smudge at 16px, so the mark is mass, and smearing the grid is how you lose it.


`extension/assets/logo-mark-large.svg` is the same letter with room to be one.
The 1024px master is a 16-cell grid taken that far: eight hard blocks with a
64px cell — which is what the reader was looking at
when they said the icon was "pixelated and very ugly". They were right, and it
was two defects at once: the grid does not survive that scale, *and* the master
had been left at 512 so whatever derived from it was upscaling it as well.

So the large mark is rasterised properly, with a scanline routine written out
below. It understands convex polygons of flat colour and nothing else, which is
exactly the vocabulary that file is allowed to use — the two facts are meant to
move together. A `path` would mean a bezier flattener in a build script.

No third-party imports, for both halves: adding Pillow to the build for one
icon would be a strange dependency to explain, and it is the build that would
carry the risk.

    python packaging/render_icon.py

Writes `packaging/icon-master.png`, the 1024px master, and the two copies the
frontend serves; and copies the extension's toolbar icons out of the desktop
icon. The desktop app's own
`kriko-gpui/assets/kriko.ico` is a separate, hand-drawn tile (the white K on
the brand blue, rounded) that the exe and the installer both read; it is not
derived here, and `test_the_desktop_icon_is_a_whole_ico` holds its shape.
"""

import re
import struct
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "extension" / "assets" / "logo-mark.svg"
#: The 1024px master. Kept under `packaging/`, outside any directory a build
#: writes into, so a build can never re-encode the committed file and leave the
#: tree dirty with a PNG nobody edited (it did exactly that once, which is how
#: this location was chosen). `test_the_committed_icon_is_what_the_mark_
#: renders_to` fails if it ever stops being what the mark renders to.
TARGET = REPO / "packaging" / "icon-master.png"
#: The same mark, served to the frontend as the rail brand and the favicon.
#: A copy rather than an import because `ui/` may not reach outside itself —
#: Vite only bundles what lives under `ui/` — and a copy that is produced by
#: the same script that produces the icon cannot drift from it. `test_brand_
#: icon.py` fails if it ever does.
WEB_TARGET = REPO / "ui" / "public" / "mark.svg"

#: The mark drawn for the sizes the grid cannot serve. See that file's own
#: comment for why there are two of them.
LARGE_SOURCE = REPO / "extension" / "assets" / "logo-mark-large.svg"
#: The large mark, served to the frontend for the rail's brand tile (B161). The
#: rail drew the 16x16 grid at 28px, a 1.75 scale, which no integer factor
#: makes crisp and which `image-rendering: pixelated` turned into uneven blocks
#: ("Fix the pixelated Kriko logo in the top left"). The drawing has real
#: diagonals and scales smoothly to any size, so the rail uses this. The grid
#: copy above stays for the favicon, where 16px is exactly one cell per pixel.
WEB_LARGE_TARGET = REPO / "ui" / "public" / "mark-large.svg"

#: 16 * 64. Kept because the extension icons and the role checks still scale
#: the grid, and because `test_the_scale_keeps_the_grid_whole` is about the
#: grid staying whole rather than about which file the master comes from.
SCALE = 64

#: The master's side. 1024 because it is the largest size anything derives
#: from it, and a smaller master means that upscales — which is exactly
#: how this shipped blurred: the file sat at 512 while
#: `test_the_master_is_large_enough` said so, in
#: a suite red enough that the line went unread.
MASTER = 1024

#: Subsamples per axis for the large mark. Four is where the diagonals stop
#: showing steps at 1024px; more buys nothing an icon can show, and this
#: routine is pure Python.
SUPERSAMPLE = 4

RECT = re.compile(
    r'<rect\s+x="(\d+)"\s+y="(\d+)"\s+width="(\d+)"\s+height="(\d+)"\s+fill="#([0-9A-Fa-f]{6})"'
)

POLYGON = re.compile(r'<polygon\s+points="([^"]+)"\s+fill="#([0-9A-Fa-f]{6})"')


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
    return _png_bytes(size, raw)


def _png_bytes(size: int, raw: bytearray) -> bytes:
    """One 8-bit RGBA PNG, from already-filtered scanlines.

    Shared by both renderers because the container is not the interesting part
    and two copies of a CRC table is how they end up differing.
    """

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


def outlines(svg: str) -> tuple[int, list[tuple[list[tuple[float, float]], tuple]]]:
    """The large mark as painted polygons, in document order.

    Rects become four points so the rasteriser has one case rather than two.
    Document order is load-bearing: the lower arm overpaints the upper where
    they cross at the spine, exactly as it does on the grid.
    """
    side = int(re.search(r'viewBox="0 0 (\d+) \d+"', svg).group(1))
    shapes: list[tuple[list[tuple[float, float]], tuple]] = []
    for match in re.finditer(r"<(?:rect|polygon)\s[^>]*?>", svg):
        piece = match.group(0)
        rect = RECT.match(piece)
        poly = POLYGON.search(piece)
        if rect:
            x, y, w, h, colour = rect.groups()
            x, y, w, h = float(x), float(y), float(w), float(h)
            points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        elif poly:
            raw, colour = poly.groups()
            points = [
                (float(pair.split(",")[0]), float(pair.split(",")[1]))
                for pair in raw.split()
            ]
        else:
            continue
        rgb = tuple(int(colour[i : i + 2], 16) for i in (0, 2, 4))
        shapes.append((points, (*rgb, 255)))
    return side, shapes


def _span(points, y: float):
    """Where a scanline crosses this polygon: (left, right), or None.

    Min and max of every edge crossing, rather than a proper even-odd fill,
    because every shape here is convex — and saying so in ten lines beats a
    general fill nobody in this repository needs. A concave mark would render
    visibly wrong in the very file the next commit shows.
    """
    hits = []
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        if y0 == y1:
            continue
        if min(y0, y1) <= y < max(y0, y1):
            hits.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return (min(hits), max(hits)) if hits else None


def smooth_png(shapes, side: int, size: int) -> bytes:
    """The large mark, antialiased, as 8-bit RGBA PNG bytes.

    Coverage is accumulated per scanline and composited in document order, so
    a shape drawn over another blends against what is already there instead of
    against the background — which is what keeps the seam where the two arms
    cross from showing as a bright edge.
    """
    scale = size / side
    raw = bytearray()
    for row in range(size):
        pixel = [(0.0, 0.0, 0.0, 0.0)] * size
        for points, (red, green, blue, _) in shapes:
            cover = [0.0] * size
            for sub in range(SUPERSAMPLE):
                found = _span(points, (row + (sub + 0.5) / SUPERSAMPLE) / scale)
                if found is None:
                    continue
                left, right = found[0] * scale, found[1] * scale
                for column in range(max(0, int(left)), min(size, int(right) + 1)):
                    overlap = min(right, column + 1) - max(left, column)
                    if overlap > 0:
                        cover[column] += overlap / SUPERSAMPLE
            for column, alpha in enumerate(cover):
                if alpha <= 0:
                    continue
                alpha = min(1.0, alpha)
                was_r, was_g, was_b, was_a = pixel[column]
                pixel[column] = (
                    was_r * (1 - alpha) + red * alpha,
                    was_g * (1 - alpha) + green * alpha,
                    was_b * (1 - alpha) + blue * alpha,
                    was_a * (1 - alpha) + 255 * alpha,
                )
        line = bytearray()
        for red, green, blue, alpha in pixel:
            line += bytes((round(red), round(green), round(blue), round(alpha)))
        raw += b"\x00" + line
    return _png_bytes(size, raw)



#: The extension's toolbar icons are the desktop app's own icon, not a render.
#: Since 1.0.1 the product has one mark, the white K on the brand plate that
#: `kriko-gpui/assets/kriko.ico` carries for the exe, the taskbar and the
#: installer. That file already holds a PNG at every size the manifest asks
#: for, so the toolbar copies those bytes out rather than drawing a second
#: version of the letter that could drift from the first.
EXTENSION_ICONS = (16, 32, 48, 128)
EXTENSION_DIR = REPO / "extension" / "assets" / "icons"
DESKTOP_ICO = REPO / "kriko-gpui" / "assets" / "kriko.ico"


PNG_SIGNATURE = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])


def ico_images(data: bytes) -> dict[int, bytes]:
    """Every PNG image in an ICO, by its side length.

    An ICO is a 6-byte header and one 16-byte entry per image (width, height,
    ..., size, offset); a width byte of 0 means 256. Only PNG entries are
    returned: a BMP entry would need a second decoder, and the desktop icon
    has none.
    """
    count = struct.unpack("<HHH", data[:6])[2]
    images = {}
    for at in range(count):
        width, _, _, _, _, _, size, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * at: 22 + 16 * at]
        )
        blob = data[offset: offset + size]
        if blob[:8] == PNG_SIGNATURE:
            images[width or 256] = blob
    return images


def offline_grid(pixels: list[list[tuple[int, int, int, int]]]) -> list[list[tuple[int, int, int, int]]]:
    """Keep the same small K, muted while the local app is unreachable."""
    ground = pixels[0][0]
    return [
        [(37, 43, 53, 255) if pixel == ground else (137, 147, 162, 255)
         for pixel in row]
        for row in pixels
    ]


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

    # The master comes from the large mark; everything below it still comes
    # from the grid. That is the whole reason there are two files: the grid is
    # right at 16px and eight hard blocks at 1024, and the master is derived
    # every app icon from this one PNG.
    units, shapes = outlines(LARGE_SOURCE.read_text(encoding="utf-8"))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(smooth_png(shapes, units, MASTER))
    print(f"{LARGE_SOURCE.name} ({units}x{units}) -> {TARGET} ({MASTER}px)")
    WEB_TARGET.parent.mkdir(parents=True, exist_ok=True)
    # newline="": `write_text` translates "\n" to "\r\n" on Windows, so
    # rendering on this host rewrote all 37 lines of a file whose content had
    # not changed at all — `aa795e6` and `bea9e88` are the same defect in
    # a config file and in the bump tool. A generated file that reports
    # itself as modified on one platform is a diff nobody can read, and the
    # frontend copy has to stay byte for byte the source anyway: a test
    # compares the two as text.
    WEB_TARGET.write_text(svg, encoding="utf-8", newline="")
    print(f"{SOURCE.name} -> {WEB_TARGET}")
    # Same newline rule as the copy above, and for the same reason: a test
    # compares this file with its source as text.
    WEB_LARGE_TARGET.write_text(
        LARGE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8", newline=""
    )
    print(f"{LARGE_SOURCE.name} -> {WEB_LARGE_TARGET}")

    EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    images = ico_images(DESKTOP_ICO.read_bytes())
    disconnected = offline_grid(pixels)
    for size in EXTENSION_ICONS:
        if size not in images:
            raise ValueError(f"{DESKTOP_ICO.name} has no {size}px PNG image")
        if size % side:
            raise ValueError(f"{size}px is not a whole multiple of {side} cells")
        (EXTENSION_DIR / f"icon-{size}.png").write_bytes(images[size])
        (EXTENSION_DIR / f"icon-offline-{size}.png").write_bytes(
            png(disconnected, size // side)
        )
    print(f"{DESKTOP_ICO.name} -> {EXTENSION_DIR}/icon-"
          f"{{{','.join(str(one) for one in EXTENSION_ICONS)}}}.png")


if __name__ == "__main__":
    main()
