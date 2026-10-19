"""Generate the KRIKO mobile art: dithered hero nebula, app icon, splash mark.

The install screens use a halftone/dither field of blue blocks that fades into
the ground colour. Generating it keeps the asset crisp, recolourable and small
instead of shipping a bitmap we cannot edit.

Run: python tools/generate_assets.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "kriko-mobile" / "assets"
SRC_ASSETS = ROOT / "kriko-mobile" / "src" / "assets"

GROUND = (3, 6, 15)
BAYER8 = np.array(
    [
        [0, 32, 8, 40, 2, 34, 10, 42],
        [48, 16, 56, 24, 50, 18, 58, 26],
        [12, 44, 4, 36, 14, 46, 6, 38],
        [60, 28, 52, 20, 62, 30, 54, 22],
        [3, 35, 11, 43, 1, 33, 9, 41],
        [51, 19, 59, 27, 49, 17, 57, 25],
        [15, 47, 7, 39, 13, 45, 5, 37],
        [63, 31, 55, 23, 61, 29, 53, 21],
    ],
    dtype=np.float64,
) / 64.0

STOPS = [
    (0.00, (5, 13, 55)),
    (0.35, (16, 44, 150)),
    (0.62, (40, 98, 255)),
    (0.84, (108, 142, 255)),
    (1.00, (176, 200, 255)),
]


def value_noise(h: int, w: int, cells: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    grid = rng.random((max(2, cells), max(2, cells))).astype(np.float32)
    small = Image.fromarray((grid * 255).astype(np.uint8), mode="L")
    up = small.resize((w, h), Image.BICUBIC)
    return np.asarray(up, dtype=np.float64) / 255.0


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def colorize(intensity: np.ndarray) -> np.ndarray:
    out = np.zeros(intensity.shape + (3,), dtype=np.float64)
    for i in range(len(STOPS) - 1):
        a, ca = STOPS[i]
        b, cb = STOPS[i + 1]
        mask = (intensity >= a) & (intensity <= b)
        t = np.clip((intensity[mask] - a) / (b - a), 0, 1)[:, None]
        out[mask] = np.array(ca) * (1 - t) + np.array(cb) * t
    out[intensity > STOPS[-1][0]] = STOPS[-1][1]
    out[intensity <= 0] = STOPS[0][1]
    return out


def hero_texture(w: int = 780, h: int = 500) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    nx, ny = xx / w, yy / h

    # Wispy cloud: several octaves of value noise pushed into a diagonal bank
    # that sits in the top right of the hero, the way the reference does.
    base = (
        0.46 * value_noise(h, w, 3, 11)
        + 0.26 * value_noise(h, w, 6, 12)
        + 0.16 * value_noise(h, w, 12, 13)
        + 0.08 * value_noise(h, w, 24, 14)
        + 0.04 * value_noise(h, w, 48, 15)
    )
    base = np.clip((base - 0.32) / 0.5, 0, 1) ** 1.25

    # Push the mass to the right and keep the left third nearly clean.
    bank = smoothstep(-0.02, 0.62, nx * 0.92 + (1 - ny) * 0.22)
    # A soft top-right bloom to echo the glow in the reference.
    dx, dy = nx - 0.86, ny - 0.10
    bloom = np.exp(-((dx * 2.1) ** 2 + (dy * 2.6) ** 2) * 5.0)
    field = base * (0.32 + 0.78 * bank) + 0.30 * bloom
    field = np.clip(field / field.max(), 0, 1) ** 1.15

    # Fade out left and bottom so the art dissolves into the ground. The left
    # third stays almost clean, as it does in the reference captures.
    alpha = smoothstep(0.06, 0.68, nx) * (1 - smoothstep(0.55, 1.02, ny))
    alpha *= 0.92

    cell = 4
    ch, cw = h // cell, w // cell
    cells = field[: ch * cell, : cw * cell].reshape(ch, cell, cw, cell).mean(axis=(1, 3))
    cell_alpha = alpha[: ch * cell, : cw * cell].reshape(ch, cell, cw, cell).mean(axis=(1, 3))

    bayer = np.tile(BAYER8, (ch // 8 + 1, cw // 8 + 1))[:ch, :cw]
    dots = (cells > bayer).astype(np.float64)
    # A faint underlying veil keeps the dither from looking like a decal.
    veil = 0.08 * cells

    colors = colorize(cells)
    rgb = np.zeros((h, w, 3), dtype=np.float64)
    a = np.zeros((h, w), dtype=np.float64)

    dot_rgb = np.repeat(np.repeat(colors, cell, axis=0), cell, axis=1)
    dot_mask = np.repeat(np.repeat(dots, cell, axis=0), cell, axis=1)
    dot_a = np.repeat(np.repeat(cell_alpha * (0.55 + 0.45 * cells), cell, axis=0), cell, axis=1)
    veil_a = np.repeat(np.repeat(veil * cell_alpha, cell, axis=0), cell, axis=1)

    rgb = dot_rgb
    a = np.where(dot_mask > 0, dot_a, veil_a)

    rgba = np.dstack([rgb, a * 255.0]).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def mark_only(size: int, bg: tuple[int, int, int] | None, fg=(255, 255, 255)):
    """Draw the wordmark mark (the K star) plus its crosshair."""
    scale = 4
    s = size * scale
    im = Image.new("RGBA", (s, s), bg + (255,) if bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = s / 44.0
    # stem
    d.rounded_rectangle(
        [int(11 * u), int(9 * u), int(21 * u), int(35 * u)], radius=int(1.2 * u), fill=fg + (255,)
    )
    # upper and lower arms
    d.polygon(
        [(int(20 * u), int(9 * u)), (int(33 * u), int(2 * u)), (int(36 * u), int(9 * u)), (int(23 * u), int(17 * u))],
        fill=fg + (255,),
    )
    d.polygon(
        [(int(20 * u), int(35 * u)), (int(33 * u), int(42 * u)), (int(36 * u), int(35 * u)), (int(23 * u), int(27 * u))],
        fill=fg + (255,),
    )
    # crosshair
    d.rectangle([int(2 * u), int(21 * u), int(42 * u), int(24 * u)], fill=fg + (255,))
    d.rectangle([int(2 * u), int(19 * u), int(5 * u), int(26 * u)], fill=fg + (255,))
    d.rectangle([int(37 * u), int(19 * u), int(42 * u), int(26 * u)], fill=fg + (255,))
    return im.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    SRC_ASSETS.mkdir(parents=True, exist_ok=True)

    hero = hero_texture()
    hero.save(SRC_ASSETS / "hero-texture.png", optimize=True)
    print("hero-texture", hero.size, (SRC_ASSETS / "hero-texture.png").stat().st_size // 1024, "KB")

    icon = Image.new("RGBA", (1024, 1024), (40, 98, 255, 255))
    d = ImageDraw.Draw(icon)
    for i in range(1024):
        v = int(255 * (0.012 * (1 - i / 1024)))
        d.line([(0, i), (1024, i)], fill=(27 + v, 70 + v, 220 + v, 255))
    m = mark_only(520, None)
    icon.alpha_composite(m, (252, 252))
    icon.save(ASSETS / "icon.png")

    fg = mark_only(620, None)
    adaptive = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    adaptive.alpha_composite(fg, (202, 202))
    adaptive.save(ASSETS / "adaptive-icon.png")

    splash = Image.new("RGBA", (512, 512), (3, 6, 15, 255))
    splash.alpha_composite(mark_only(260, None), (126, 126))
    splash.save(ASSETS / "splash-icon.png")

    print("icons written to", ASSETS)


if __name__ == "__main__":
    main()
