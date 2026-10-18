"""Instance the display face used by the mobile app's screen titles.

The reference titles are a condensed grotesque: measured against the capture,
"SET UP" is 100 px wide at a 29 px cap height, which Geist Bold misses by 43 px.
Archivo's variable font carries a `wdth` axis (62-125), so we pin the narrow end
and save a static instance the app can load in Expo Go.

Run: python tools/make_fonts.py
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".fonts" / "Archivo-var.ttf"
OUT = ROOT / "kriko-mobile" / "assets" / "fonts"

# The variable source, from the Google Fonts repository.
SOURCE_URL = "https://github.com/google/fonts/raw/main/ofl/archivo/Archivo%5Bwdth%2Cwght%5D.ttf"

# (family, weight, width axis, output file)
FACES = [
    ("Kriko Display", 700, 62, "KrikoDisplay-Bold.ttf"),
    ("Kriko Display", 600, 62, "KrikoDisplay-SemiBold.ttf"),
]


def build(family: str, weight: int, wdth: float, out_name: str) -> Path:
    font = TTFont(str(SRC))
    inst = instantiateVariableFont(font, {"wdth": wdth, "wght": weight}, inplace=False, updateFontNames=False)
    style = "Regular" if weight == 400 else ("Bold" if weight == 700 else "SemiBold")
    postscript = family.replace(" ", "") + "-" + style
    for record in inst["name"].names:
        if record.nameID in (1, 16):
            record.string = family
        elif record.nameID in (2, 17):
            record.string = style
        elif record.nameID == 4:
            record.string = f"{family} {style}"
        elif record.nameID == 6:
            record.string = postscript
    inst["OS/2"].usWeightClass = weight
    out = OUT / out_name
    inst.save(str(out))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        SRC.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {SOURCE_URL}")
        urllib.request.urlretrieve(SOURCE_URL, SRC)
    for family, weight, wdth, name in FACES:
        path = build(family, weight, wdth, name)
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
