"""Turn the pictures from capture.mjs and capture-app.mjs into WebP and delete the PNGs.

    python3 site/tools/optimise_images.py

Pillow is the only requirement. The panel pictures keep their transparent
corners; the pictures beside a listing have none to keep. The desktop pictures
are whole windows with no transparency, so a slightly lower quality does them no
harm and keeps the page light.
"""

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"
QUALITY = {"examples": 88, "desktop": 82}

for folder, quality in QUALITY.items():
    for source in sorted((ASSETS / folder).glob("*.png")):
        image = Image.open(source)
        image.save(source.with_suffix(".webp"), "WEBP", quality=quality, method=6)
        source.unlink()
        print(f"{folder}/{source.with_suffix('.webp').name}", source.with_suffix(".webp").stat().st_size // 1024, "KB")
