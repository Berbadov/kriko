"""Check which font and size reproduces the reference type measurements.

Reference measurements are in logical pixels (the design is a 2x capture):
  H1 "SET UP"        cap height 29, width 100
  subtitle line 1    cap/ascender run 11.5, width 283

Run: python tools/measure_type.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
NM = ROOT / "kriko-mobile" / "node_modules"
GEIST = NM / "@expo-google-fonts" / "geist"
MONO = NM / "@expo-google-fonts" / "geist-mono"
ARCHIVO = ROOT / ".fonts" / "Archivo-var.ttf"
TMP = ROOT / ".fonts"


def cap_ratio(path: Path) -> float:
    font = TTFont(str(path))
    upm = font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight
    return cap / upm


def text_width(path: Path, size: float, text: str) -> float:
    font = ImageFont.truetype(str(path), int(round(size * 8)))
    return font.getlength(text) / 8


def report(label: str, path: Path, text: str, target_cap: float, target_w: float) -> None:
    ratio = cap_ratio(path)
    size = target_cap / ratio
    width = text_width(path, size, text)
    print(
        f"{label:34s} cap_ratio={ratio:.3f} size_for_cap={size:5.1f} "
        f"width={width:6.1f} target={target_w:6.1f} delta={width - target_w:+6.1f}"
    )


def instance(wdth: float, wght: float) -> Path:
    out = TMP / f"Archivo-wdth{int(wdth)}-wght{int(wght)}.ttf"
    if out.exists():
        return out
    font = TTFont(str(ARCHIVO))
    axes = {"wdth": wdth, "wght": wght}
    inst = instantiateVariableFont(font, axes, inplace=False, updateFontNames=False)
    family = f"Archivo Condensed {int(wght)}"
    for record in inst["name"].names:
        if record.nameID in (1, 16):
            record.string = family
        elif record.nameID in (2, 17):
            record.string = "Regular"
        elif record.nameID == 4:
            record.string = family
        elif record.nameID == 6:
            record.string = f"ArchivoCondensed-{int(wght)}"
    inst.save(str(out))
    return out


def main() -> None:
    print("axes:", [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in TTFont(str(ARCHIVO))["fvar"].axes])
    print()
    print("--- H1 (SET UP): target cap 29, width 100 ---")
    report("Geist 700", GEIST / "700Bold" / "Geist_700Bold.ttf", "SET UP", 29, 100)
    report("Geist 800", GEIST / "800ExtraBold" / "Geist_800ExtraBold.ttf", "SET UP", 29, 100)
    report("Geist 900", GEIST / "900Black" / "Geist_900Black.ttf", "SET UP", 29, 100)
    for wdth in (70, 75, 80, 85, 90, 100):
        for wght in (700, 800):
            p = instance(wdth, wght)
            report(f"Archivo wdth{wdth} wght{wght}", p, "SET UP", 29, 100)
    print()
    print("--- subtitle: target ascender run ~11.5, width 283 ---")
    line = "Download the reader once. It runs on this"
    for label, path in [
        ("Geist 400", GEIST / "400Regular" / "Geist_400Regular.ttf"),
        ("Geist 500", GEIST / "500Medium" / "Geist_500Medium.ttf"),
    ]:
        f = TTFont(str(path))
        upm = f["head"].unitsPerEm
        asc = f["hhea"].ascent / upm
        size = 11.5 / asc
        print(f"{label:34s} asc_ratio={asc:.3f} size_for_run={size:5.1f} width={text_width(path, size, line):6.1f} (target 283)")
    print()
    print("--- mono breadcrumb 'kriko / set up': target width ~ (34..?) ---")
    for label, path in [("GeistMono 400", MONO / "400Regular" / "GeistMono_400Regular.ttf")]:
        f = TTFont(str(path))
        upm = f["head"].unitsPerEm
        print(f"{label} cap_ratio={f['OS/2'].sCapHeight / upm:.3f} adv_ratio={f['hmtx']['a'][0] / upm:.3f}")


if __name__ == "__main__":
    sys.exit(main())
