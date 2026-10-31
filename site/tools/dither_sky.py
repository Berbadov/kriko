"""Draw the website's dithered sky pictures with the same method as the app.

    python3 site/tools/dither_sky.py

The app's home screen draws a cloud field through an 8x8 ordered dither into a
small palette (kriko-ui/src/ui/DitherSky.tsx). This is that method, run once,
so the site wears the same sky. Each picture is small on purpose and is scaled
up with hard pixel edges in CSS. Pillow is the only requirement.
"""

from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "assets" / "sky"

PALETTES = {
    # One ramp per theme: the product's own blue, from pale to deep. No second
    # hue, so the dither reads as sky and not as confetti.
    "light": {
        "sky": ["#8fa6ff", "#6a8cf0", "#a9bcff"],
        "cloud": ["#f4f7ff", "#e3ebff", "#cdd9ff", "#b9c8ff", "#dfe7ff"],
    },
    "dark": {
        "sky": ["#0a1230", "#16277e", "#2447e6"],
        "cloud": ["#16215f", "#2447e6", "#3d63f5", "#5c7bff", "#9db3ff"],
    },
}


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def bayer(n=8):
    m = [[0]]
    size = 1
    while size < n:
        nxt = [[0] * (size * 2) for _ in range(size * 2)]
        for y in range(size):
            for x in range(size):
                v = m[y][x] * 4
                nxt[y][x] = v
                nxt[y][x + size] = v + 2
                nxt[y + size][x] = v + 3
                nxt[y + size][x + size] = v + 1
        m, size = nxt, size * 2
    return [[(v + 0.5) / (n * n) for v in row] for row in m]


BAYER = bayer()


def hash_(x, y, seed):
    h = (x * 374761393 + y * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFFFF) / 4294967295


def noise(x, y, period, seed):
    x0, y0 = int(x // 1), int(y // 1)
    fx, fy = x - x0, y - y0
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = hash_(x0 % period, y0, seed)
    b = hash_((x0 + 1) % period, y0, seed)
    c = hash_(x0 % period, y0 + 1, seed)
    d = hash_((x0 + 1) % period, y0 + 1, seed)
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy


def field(width, height):
    values = []
    for y in range(height):
        row = []
        for x in range(width):
            value, amp, total = 0.0, 0.55, 0.0
            for octave in range(5):
                cells = 6 * 2 ** octave
                value += amp * noise(x / width * cells, y / height * cells * 0.62, cells, octave + 3)
                total += amp
                amp *= 0.5
            row.append(value / total)
        values.append(row)
    return values


def draw(name, theme, width, height, *, side=1.05, floor=0.18, shift=0):
    palette = PALETTES[theme]
    sky = [rgb(c) for c in palette["sky"]]
    cloud = [rgb(c) for c in palette["cloud"]]
    base = field(width * 2, height)
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        fy = y / height
        for x in range(width):
            fx = x / width
            edge = abs(fx - 0.5) * 2
            mask = floor + side * edge ** 1.4
            fade = max(0.0, 1 - fy * 1.12)
            density = base[y][(x + shift) % (width * 2)] * mask * (0.35 + fade)
            b = BAYER[y & 7][x & 7]
            if density < 0.36:
                level = min(2, int(fy * 2.2 + b * 1.15))
                pixels[x, y] = sky[level]
            else:
                t = (density - 0.36) / 0.34
                level = max(0, min(len(cloud) - 1, int(t * (len(cloud) - 1) + b)))
                pixels[x, y] = cloud[level]
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / f"{name}-{theme}.webp", "WEBP", lossless=True, method=6)
    print(f"{name}-{theme}.webp", (OUT / f"{name}-{theme}.webp").stat().st_size // 1024, "KB")


for theme in ("light", "dark"):
    draw("stage", theme, 176, 196, side=1.25, floor=0.5, shift=40)
    draw("band", theme, 384, 54, side=0.9, floor=0.3, shift=210)
