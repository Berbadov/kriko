"""Render the sample listing screenshot the app falls back to.

A fresh emulator has no photos in its library, so "share a screenshot" needs a
stand-in. This draws a plausible store listing page: it names the product and
the model number is genuinely absent, which is what the check screen reports.

Run: python tools/generate_sample_shot.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kriko-mobile" / "src" / "assets" / "sample-listing.png"

W, H = 820, 1640
FONTS = Path("C:/Windows/Fonts")

BG = (11, 13, 20)
CARD = (22, 25, 38)
INK = (238, 241, 249)
INK2 = (168, 176, 196)
ACCENT = (40, 98, 255)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (FONTS / name, FONTS / "segoeui.ttf", FONTS / "arial.ttf"):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> None:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    regular = font("segoeui.ttf", 26)
    small = font("segoeui.ttf", 22)
    bold = font("segoeuib.ttf", 34)
    heavy = font("segoeuib.ttf", 44)

    # Status bar and store header.
    d.text((28, 22), "9:41", font=small, fill=INK)
    d.text((W - 130, 22), "5G  100%", font=small, fill=INK)
    d.rectangle([0, 70, W, 150], fill=(15, 18, 28))
    d.text((28, 95), "shop.test", font=bold, fill=INK)
    d.text((W - 96, 96), "search", font=small, fill=INK2)

    # Product image panel.
    d.rounded_rectangle([28, 180, W - 28, 720], radius=28, fill=CARD)
    for i in range(120):
        shade = (18 + i // 6, 30 + i // 4, 70 + i // 2)
        d.rounded_rectangle(
            [28 + i, 180 + i, W - 28 - i, 720 - i],
            radius=max(2, 28 - i // 5),
            outline=shade,
        )
    # Two earbuds, drawn as soft discs.
    for cx, cy, r in ((330, 440, 78), (500, 470, 66)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(38, 44, 62), outline=(70, 84, 120), width=2)
        d.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3], fill=(24, 28, 42))
    d.rounded_rectangle([250, 600, 570, 680], radius=24, fill=(30, 34, 50))
    d.text((286, 622), "Galaxy Buds2 Pro", font=regular, fill=INK2)

    # Title block.
    d.text((28, 760), "Samsung Galaxy Buds2 Pro", font=heavy, fill=INK)
    d.text((28, 826), "True Wireless Earbuds · ANC · Graphite", font=small, fill=INK2)
    # Five filled stars, drawn as polygons so no font has to carry the glyph.
    import math

    for i in range(5):
        cx, cy, r = 44 + i * 34, 890, 14
        pts = []
        for k in range(10):
            angle = -math.pi / 2 + k * math.pi / 5
            radius = r if k % 2 == 0 else r * 0.45
            pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        d.polygon(pts, fill=(245, 184, 75))
    d.text((222, 874), "4.6 · 12,904 reviews", font=small, fill=INK2)
    d.text((28, 940), "$189.00", font=heavy, fill=INK)
    d.text((200, 962), "was $229.00", font=small, fill=INK2)

    d.line([28, 1030, W - 28, 1030], fill=(38, 44, 62), width=2)
    bullets = [
        "Active noise cancelling with 3 microphones",
        "Up to 6 h play time with ANC on, 8 h with it off",
        "Wireless charging case, 18 h total",
        "IPX7 water resistant",
    ]
    y = 1070
    for line in bullets:
        d.ellipse([34, y + 12, 44, y + 22], fill=ACCENT)
        d.text((64, y), line, font=regular, fill=INK)
        y += 64

    d.rounded_rectangle([28, y + 24, W - 28, y + 204], radius=24, fill=CARD)
    d.text((52, y + 52), "Model number", font=small, fill=INK2)
    d.text((52, y + 92), "Not shown on this page", font=regular, fill=(120, 128, 148))
    d.text((52, y + 140), "Sold by shop.test", font=small, fill=INK2)

    d.rounded_rectangle([28, H - 130, W - 28, H - 44], radius=26, fill=ACCENT)
    label = "Add to basket"
    w = d.textlength(label, font=bold)
    d.text(((W - w) / 2, H - 106), label, font=bold, fill=(255, 255, 255))

    im.save(OUT, optimize=True)
    print("wrote", OUT.relative_to(ROOT), im.size, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
