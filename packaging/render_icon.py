"""Render the brand mark to the 1024px master PNG and extension icons.

There is one mark, `extension/assets/logo-mark-large.svg`, and every icon is a
render of it. It is rasterised properly, with a scanline routine written out
below. It understands convex polygons of flat colour and nothing else, which is
exactly the vocabulary that file is allowed to use — the two facts are meant to
move together. A `path` would mean a bezier flattener in a build script.

The mark has a detail and a silhouette: the white and grey split copies of the
jack behind it are a large-size detail, and below 64px they smear into a dark
diamond (that was the "hideous" toolbar icon). So sizes up to 48px render the
mark solid — plate and jack only — and everything above renders the full split.
No size renders the old 16-cell grid: the jack's staircase arms on that grid
read as a blob at 16px, which is how a pixel-art letter ends up uglier than the
smooth one it was drawn to protect.

No third-party imports: adding Pillow to the build for one icon would be a
strange dependency to explain, and it is the build that would carry the risk.

    python packaging/render_icon.py

Writes `packaging/icon-master.png`, the 1024px master, and the desktop app's own
`kriko-ui/src-tauri/icons/icon.ico`, the tile the exe and the installer read.
The extension toolbar icons are copied out of that ICO, and the Tauri PNGs
beside it, the phone app's icon, Android foreground, splash and favicon all
come from the same source, so there is one drawing of the mark and every size
is a render of it.
"""

import re
import struct
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: The 1024px master. Kept under `packaging/`, outside any directory a build
#: writes into, so a build can never re-encode the committed file and leave the
#: tree dirty with a PNG nobody edited (it did exactly that once, which is how
#: this location was chosen). `test_the_committed_icon_is_what_the_mark_
#: renders_to` fails if it ever stops being what the mark renders to.
TARGET = REPO / "packaging" / "icon-master.png"
#: The one drawing of the mark. See the module docstring for the solid/split
#: split by size.
LARGE_SOURCE = REPO / "extension" / "assets" / "logo-mark-large.svg"
#: Sizes up to this render the mark solid (plate and jack); above it the full
#: mark with the white and grey split copies. 48 is where the split starts to
#: read as a third colour instead of noise.
SMALL_MAX = 48

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
#: Since 1.0.1 the product has one mark, the jack on its grey plate that
#: `kriko-ui/src-tauri/icons/icon.ico` carries for the exe, the taskbar and the
#: installer. That file already holds a PNG at every size the manifest asks
#: for, so the toolbar copies those bytes out rather than drawing a second
#: version of the letter that could drift from the first.
EXTENSION_ICONS = (16, 32, 48, 128)
EXTENSION_DIR = REPO / "extension" / "assets" / "icons"
DESKTOP_ICO = REPO / "kriko-ui" / "src-tauri" / "icons" / "icon.ico"


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


def small_shapes(shapes):
    """The mark without the split: plate plus the jack, for sizes up to SMALL_MAX.

    The first shape is the plate; of the rest, the jack is whatever shares the
    darkest ink, and the white/grey split copies are everything lighter. At
    48px and below those copies smear into a dark diamond, so they are dropped
    and the silhouette carries the icon.
    """
    plate, rest = shapes[0], shapes[1:]
    ink = min(rest, key=lambda shape: sum(shape[1][:3]))[1]
    return [plate] + [shape for shape in rest if shape[1] == ink]


def muted(shapes):
    """The same shapes, muted while the local app is unreachable.

    Light fills (plate and split copies) go to a dark ground and the dark jack
    goes to a light one, so the offline icon is visibly the same letter in a
    quieter state rather than a copy of the online one.
    """
    ground, letter = (37, 43, 53, 255), (137, 147, 162, 255)
    return [
        (points, letter if sum(colour[:3]) < 200 else ground)
        for points, colour in shapes
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


#: The ICO's sizes. Up to SMALL_MAX the mark renders solid; above it, with the
#: split. Every size is the smooth rasteriser — no size renders pixel art.
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
#: The PNGs Tauri and the Windows store tiles read, by file name.
TAURI_PNGS = {
    "32x32.png": 32, "128x128.png": 128, "128x128@2x.png": 256, "icon.png": 512,
    "Square30x30Logo.png": 30, "Square44x44Logo.png": 44, "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89, "Square107x107Logo.png": 107, "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150, "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310, "StoreLogo.png": 50,
}


def shapes_for(shapes, size: int):
    """The shapes one size renders: the mark solid up to SMALL_MAX, the full split above."""
    return small_shapes(shapes) if size <= SMALL_MAX else shapes


def at_size(shapes, units: int, size: int) -> bytes:
    """One size of the icon, antialiased, from the shapes that size draws."""
    return smooth_png(shapes_for(shapes, size), units, size)


def ico(images: dict[int, bytes]) -> bytes:
    """An ICO of PNG entries, smallest first; a side of 256 is written as 0."""
    sizes = sorted(images)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset, entries, data = 6 + 16 * len(sizes), b"", b""
    for side in sizes:
        blob = images[side]
        entries += struct.pack("<BBBBHHII", side % 256, side % 256, 0, 0, 1, 32,
                               len(blob), offset + len(data))
        data += blob
    return header + entries + data


#: The phone app's images, read by `kriko-mobile/app.json`.
MOBILE_DIR = REPO / "kriko-mobile" / "assets"
#: Android shows only the middle 72 of an adaptive icon's 108dp, so its
#: foreground carries the mark at two thirds of the size the plate does,
#: which leaves it the same share of what the launcher actually shows.
ADAPTIVE_SHARE = 72 / 108


def reframed(shapes, side: int, factor: float = 1.0, ground: bool = True):
    """The large mark for a phone: the plate (the first shape) made a full
    square, because iOS and Android cut their own corners, or dropped for a
    transparent foreground; the mark scaled by `factor` about the tile's middle.
    """
    plate, mark = shapes[0], shapes[1:]
    middle = side / 2
    def move(x: float, y: float) -> tuple[float, float]:
        return middle + (x - middle) * factor, middle + (y - middle) * factor

    moved = [([move(x, y) for x, y in points], colour) for points, colour in mark]
    if not ground:
        return moved
    return [([(0, 0), (side, 0), (side, side), (0, side)], plate[1])] + moved


def mobile_images(shapes, units: int) -> dict[str, bytes]:
    """Every image the phone app ships, by file name."""
    return {
        "icon.png": smooth_png(reframed(shapes, units), units, MASTER),
        "adaptive-icon.png": smooth_png(
            reframed(shapes, units, ADAPTIVE_SHARE, ground=False), units, MASTER
        ),
        "splash-icon.png": smooth_png(shapes, units, MASTER),
        "favicon.png": smooth_png(shapes, units, 64),
    }


def main() -> None:
    # One drawing of the mark; every size is a render of it. The master and
    # anything above SMALL_MAX carry the split, the small sizes are solid.
    units, shapes = outlines(LARGE_SOURCE.read_text(encoding="utf-8"))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(smooth_png(shapes, units, MASTER))
    print(f"{LARGE_SOURCE.name} ({units}x{units}) -> {TARGET} ({MASTER}px)")
    DESKTOP_ICO.write_bytes(ico({one: at_size(shapes, units, one) for one in ICO_SIZES}))
    for name, size in TAURI_PNGS.items():
        (DESKTOP_ICO.parent / name).write_bytes(at_size(shapes, units, size))
    print(f"-> {DESKTOP_ICO} and {len(TAURI_PNGS)} Tauri PNGs")
    EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    images = ico_images(DESKTOP_ICO.read_bytes())
    for size in EXTENSION_ICONS:
        if size not in images:
            raise ValueError(f"{DESKTOP_ICO.name} has no {size}px PNG image")
        (EXTENSION_DIR / f"icon-{size}.png").write_bytes(images[size])
        (EXTENSION_DIR / f"icon-offline-{size}.png").write_bytes(
            smooth_png(muted(shapes_for(shapes, size)), units, size)
        )
    print(f"{DESKTOP_ICO.name} -> {EXTENSION_DIR}/icon-"
          f"{{{','.join(str(one) for one in EXTENSION_ICONS)}}}.png")
    if MOBILE_DIR.is_dir():
        for name, blob in mobile_images(shapes, units).items():
            (MOBILE_DIR / name).write_bytes(blob)
        print(f"-> {MOBILE_DIR}")


if __name__ == "__main__":
    main()
