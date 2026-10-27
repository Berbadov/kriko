"""Contact sheet of stills: python sheet.py out/sheet.png 1.5 6 12 (run from site/tools/ad)."""
import sys, glob, os
from PIL import Image, ImageDraw
names = sys.argv[2:]
files = []
for n in names:
    t = float(n)
    s = str(int(t)) if t == int(t) else str(t)
    files.append(f"out/stills/t-{s.rjust(5,'0')}.png")
cols = 3
w, h = 800, 450
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * h), "white")
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB").resize((w, h), Image.LANCZOS)
    d = ImageDraw.Draw(im); d.text((8, 6), names[i] + "s", fill=(255, 0, 255))
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(sys.argv[1])
