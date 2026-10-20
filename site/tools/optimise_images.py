"""Turn the example pictures from capture.mjs into WebP and delete the PNGs.

    python3 site/tools/optimise_images.py

Pillow is the only requirement. The panel pictures keep their transparent
corners; the pictures beside a listing have none to keep.
"""

from pathlib import Path

from PIL import Image

FOLDER = Path(__file__).resolve().parents[1] / "assets" / "examples"

for source in sorted(FOLDER.glob("*.png")):
    image = Image.open(source)
    image.save(source.with_suffix(".webp"), "WEBP", quality=88, method=6)
    source.unlink()
    print(source.with_suffix(".webp").name, source.with_suffix(".webp").stat().st_size // 1024, "KB")
