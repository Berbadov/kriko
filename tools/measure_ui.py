"""Recover the reference type scale from the design captures.

For each piece of text we take the ink bounding box in the 2x capture, then ask
the real font files how large the type must be to produce that ink width. The
answer is what the theme tokens are built from.

Run: python tools/measure_ui.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / ".preview"
NM = ROOT / "kriko-mobile" / "node_modules"
GEIST = NM / "@expo-google-fonts" / "geist"
MONO = NM / "@expo-google-fonts" / "geist-mono"
ARCHIVO = ROOT / ".fonts" / "Archivo-wdth62-wght700.ttf"

SANS = {
    400: GEIST / "400Regular" / "Geist_400Regular.ttf",
    500: GEIST / "500Medium" / "Geist_500Medium.ttf",
    600: GEIST / "600SemiBold" / "Geist_600SemiBold.ttf",
    700: GEIST / "700Bold" / "Geist_700Bold.ttf",
}
MONOS = {400: MONO / "400Regular" / "GeistMono_400Regular.ttf", 500: MONO / "500Medium" / "GeistMono_500Medium.ttf"}


@dataclass
class Probe:
    shot: str
    label: str
    box: tuple[int, int, int, int]
    text: str
    font: Path
    tracking: float = 0.0  # letter-spacing in the reference, in em
    upper: bool = False


PROBES = [
    Probe("s1", "breadcrumb", (28, 155, 460, 200), "kriko / set up", MONOS[400], 0.14),
    Probe("s1", "h1", (28, 214, 300, 292), "SET UP", ARCHIVO),
    Probe("s1", "subtitle", (28, 305, 740, 345), "Download the reader once. It runs on this", SANS[400]),
    Probe("s1", "card title", (150, 462, 620, 505), "Reader model", SANS[600]),
    Probe("s1", "card mono sub", (150, 508, 620, 550), "[MODEL ID] . [SIZE]", MONOS[400], 0.04),
    Probe("s1", "progress label", (55, 580, 400, 625), "Downloading", SANS[400]),
    Probe("s1", "progress pct", (610, 580, 740, 625), "39%", MONOS[400]),
    Probe("s1", "toggle title", (55, 692, 400, 738), "Wi-Fi only", SANS[600]),
    Probe("s1", "toggle body", (55, 740, 570, 785), "Pause the download on mobile", SANS[400]),
    Probe("s1", "privacy title", (120, 875, 620, 920), "What leaves this phone", SANS[600]),
    Probe("s1", "privacy body", (120, 922, 660, 962), "Screenshots are read here and never", SANS[400]),
    Probe("s1", "button", (150, 1535, 620, 1585), "START CHATTING", SANS[700], 0.12),
    Probe("s2", "section label", (28, 596, 300, 640), "Try asking", SANS[600]),
    Probe("s2", "suggestion", (115, 690, 680, 730), "Wireless earbuds with noise canceling", SANS[400]),
    Probe("s2", "placeholder", (55, 1500, 600, 1545), "Describe a product...", SANS[400]),
    Probe("s2", "chip label", (80, 1445, 260, 1485), "READY", SANS[700], 0.10),
    Probe("s3", "field label", (60, 762, 400, 800), "Brand", SANS[400]),
    Probe("s3", "field value", (60, 805, 400, 855), "Samsung", SANS[700]),
    Probe("s5", "claim title", (60, 610, 300, 660), "Battery life", SANS[600]),
    Probe("s5", "claim body", (60, 668, 700, 710), "6 h with noise cancelling on. Four sources agree.", SANS[400]),
]


def ink_box(shot: str, box: tuple[int, int, int, int], thr: int = 150) -> tuple[int, int, int, int] | None:
    im = Image.open(PREVIEW / f"{shot}.png").convert("RGB")
    x0, y0, x1, y1 = box
    px = im.load()
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            r, g, b = px[x, y]
            if (r + g + b) / 3 > thr:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def measure(path: Path, size: float, text: str, tracking: float) -> float:
    font = ImageFont.truetype(str(path), int(round(size * 10)))
    width = font.getlength(text) / 10
    # letter-spacing applies after every glyph in CSS/RN; approximate on all but the last.
    return width + tracking * size * max(0, len(text) - 1)


def solve(path: Path, text: str, tracking: float, target_w: float) -> float:
    lo, hi = 4.0, 90.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if measure(path, mid, text, tracking) < target_w:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cap_height(path: Path, size: float) -> float:
    from fontTools.ttLib import TTFont

    f = TTFont(str(path))
    return f["OS/2"].sCapHeight / f["head"].unitsPerEm * size


def main() -> None:
    for p in PROBES:
        ib = ink_box(p.shot, p.box)
        if ib is None:
            print(f"{p.shot} {p.label:16s} NO INK in {p.box}")
            continue
        x0, y0, x1, y1 = ib
        w2, h2 = x1 - x0 + 1, y1 - y0 + 1
        w, h = w2 / 2, h2 / 2
        size = solve(p.font, p.text, p.tracking, w)
        cap = cap_height(p.font, size)
        print(
            f"{p.shot} {p.label:16s} ink={w:6.1f}x{h:5.1f}  ->  size={size:5.2f}  cap={cap:5.2f}  "
            f"({p.text[:34]!r})"
        )


if __name__ == "__main__":
    main()
