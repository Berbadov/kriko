"""Put a screenshot next to its design reference, at the same scale.

Both images are normalised to the reference's width, then written as one sheet:
reference on the left, the build in the middle, and a 50 % blend on the right so
a shift of a couple of pixels is visible.

Run: python tools/compare.py chat .preview/shots/v2_chat.png 2
     (the number is the reference screen: 1..5)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / ".preview"
REF_W, REF_H = 780, 1688


def load_shot(path: Path) -> Image.Image:
    """Crop the Android status bar: start at the first row of brand blue."""
    shot = Image.open(path).convert("RGB")
    w, h = shot.size
    px = shot.load()
    for y in range(min(h, int(h * 0.2))):
        r, g, b = px[w // 2, y]
        if abs(r - 40) < 26 and abs(g - 98) < 26 and abs(b - 255) < 26:
            return shot.crop((0, y, w, h))
    return shot


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: compare.py <name> <shot.png> <ref 1..5>")
    name = sys.argv[1]
    shot_path = Path(sys.argv[2])
    ref_no = int(sys.argv[3])

    ref = Image.open(PREVIEW / f"s{ref_no}.png").convert("RGB")
    shot = load_shot(shot_path if shot_path.is_absolute() else ROOT / shot_path)

    scale = REF_W / shot.width
    shot = shot.resize((REF_W, round(shot.height * scale)), Image.LANCZOS)
    shot = shot.crop((0, 0, REF_W, min(REF_H, shot.height)))
    if shot.height < REF_H:
        canvas = Image.new("RGB", (REF_W, REF_H), (3, 6, 15))
        canvas.paste(shot, (0, 0))
        shot = canvas

    blend = Image.blend(ref, shot, 0.5)
    sheet = Image.new("RGB", (REF_W * 3 + 32, REF_H), (24, 24, 28))
    for i, img in enumerate((ref, shot, blend)):
        sheet.paste(img, (i * (REF_W + 16), 0))
    out = PREVIEW / f"compare_{name}.png"
    sheet.save(out)
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
