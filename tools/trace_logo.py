"""Trace the KRIKO wordmark out of the design reference into SVG path data.

The wordmark is white on the brand blue, so the red channel is already an
alpha mask. We upsample it, run marching squares at the 0.5 level to get
smooth contours, simplify them with Douglas-Peucker, and emit path data for
react-native-svg.

Run: python tools/trace_logo.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".preview" / "s1.png"
OUT = ROOT / "kriko-mobile" / "src" / "assets" / "logoPaths.ts"

# Wordmark bounds in the 780px-wide reference (measured from the pixel mask).
BOX = (31, 36, 168, 83)
UPSCALE = 6
LEVEL = 0.5
EPSILON = 1.6  # in upscaled pixels


def extract_alpha() -> Image.Image:
    im = Image.open(SRC).convert("RGB")
    crop = im.crop(BOX)
    w, h = crop.size
    out = Image.new("L", (w, h))
    src = crop.load()
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r = src[x, y][0]
            dst[x, y] = max(0, min(255, round((r - 40) * 255 / 215)))
    return out.resize((w * UPSCALE, h * UPSCALE), Image.BICUBIC)


def edge_points(field, x, y, level):
    tl, tr, br, bl = field[y][x], field[y][x + 1], field[y + 1][x + 1], field[y + 1][x]

    def top():
        t = (level - tl) / (tr - tl) if tr != tl else 0.5
        return (x + t, y)

    def right():
        t = (level - tr) / (br - tr) if br != tr else 0.5
        return (x + 1, y + t)

    def bottom():
        t = (level - bl) / (br - bl) if br != bl else 0.5
        return (x + t, y + 1)

    def left():
        t = (level - tl) / (bl - tl) if bl != tl else 0.5
        return (x, y + t)

    return top, right, bottom, left


TABLE = {
    1: ("left", "top"),
    2: ("top", "right"),
    3: ("left", "right"),
    4: ("right", "bottom"),
    6: ("top", "bottom"),
    7: ("left", "bottom"),
    8: ("left", "bottom"),
    9: ("top", "bottom"),
    11: ("right", "bottom"),
    12: ("left", "right"),
    13: ("top", "right"),
    14: ("left", "top"),
}


def marching_squares(field, level=LEVEL):
    h = len(field)
    w = len(field[0])
    segments = []
    for y in range(h - 1):
        for x in range(w - 1):
            tl, tr = field[y][x], field[y][x + 1]
            br, bl = field[y + 1][x + 1], field[y + 1][x]
            case = (1 if tl >= level else 0) | (2 if tr >= level else 0)
            case |= (4 if br >= level else 0) | (8 if bl >= level else 0)
            if case == 0 or case == 15:
                continue
            top, right, bottom, left = edge_points(field, x, y, level)
            handle = {"top": top, "right": right, "bottom": bottom, "left": left}
            if case in TABLE:
                a, b = TABLE[case]
                segments.append((handle[a](), handle[b]()))
            elif case == 5:
                center = (tl + tr + br + bl) / 4
                if center >= level:
                    segments.append((handle["left"](), handle["top"]()))
                    segments.append((handle["right"](), handle["bottom"]()))
                else:
                    segments.append((handle["left"](), handle["bottom"]()))
                    segments.append((handle["top"](), handle["right"]()))
            else:  # case 10
                center = (tl + tr + br + bl) / 4
                if center >= level:
                    segments.append((handle["top"](), handle["left"]()))
                    segments.append((handle["bottom"](), handle["right"]()))
                else:
                    segments.append((handle["top"](), handle["right"]()))
                    segments.append((handle["left"](), handle["bottom"]()))
    return segments


def key(p):
    return (round(p[0], 3), round(p[1], 3))


def build_loops(segments):
    from collections import defaultdict

    adjacency = defaultdict(list)
    for i, (a, b) in enumerate(segments):
        adjacency[key(a)].append((i, key(b), b))
        adjacency[key(b)].append((i, key(a), a))

    used: set[int] = set()
    loops = []
    for i, (a, b) in enumerate(segments):
        if i in used:
            continue
        used.add(i)
        loop = [a, b]
        start, current = key(a), key(b)
        while current != start:
            step = next((entry for entry in adjacency[current] if entry[0] not in used), None)
            if step is None:
                break
            j, other_key, other_point = step
            used.add(j)
            loop.append(other_point)
            current = other_key
        if key(loop[-1]) == key(loop[0]):
            loop = loop[:-1]
        if len(loop) > 3:
            loops.append(loop)
    return loops


def rdp(points, epsilon):
    if len(points) < 3:
        return points
    first, last = points[0], points[-1]
    dx, dy = last[0] - first[0], last[1] - first[1]
    norm = math.hypot(dx, dy)
    best, best_i = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm == 0:
            dist = math.hypot(px - first[0], py - first[1])
        else:
            dist = abs(dy * px - dx * py + last[0] * first[1] - last[1] * first[0]) / norm
        if dist > best:
            best, best_i = dist, i
    if best <= epsilon:
        return [first, last]
    left = rdp(points[: best_i + 1], epsilon)
    right = rdp(points[best_i:], epsilon)
    return left[:-1] + right


def simplify_closed(points, epsilon):
    # Split the closed loop at its farthest pair to keep RDP stable.
    n = len(points)
    far = max(range(n), key=lambda i: math.dist(points[0], points[i]))
    a = rdp(points[: far + 1], epsilon)
    b = rdp(points[far:] + [points[0]], epsilon)
    return a[:-1] + b[:-1]


def main() -> None:
    alpha = extract_alpha()
    w, h = alpha.size
    raw = alpha.load()
    field = [[raw[x, y] / 255.0 for x in range(w)] for y in range(h)]
    loops = build_loops(marching_squares(field))
    scale = 1.0 / UPSCALE

    parts = []
    total_points = 0
    for loop in loops:
        pts = simplify_closed(loop, EPSILON)
        total_points += len(pts)
        if len(pts) < 3:
            continue
        cmds = []
        for i, (x, y) in enumerate(pts):
            cx, cy = x * scale, y * scale
            cmds.append(f"{'M' if i == 0 else 'L'}{cx:.2f} {cy:.2f}")
        cmds.append("Z")
        parts.append("".join(cmds))

    path = "".join(parts)
    width, height = (BOX[2] - BOX[0]) * 1.0, (BOX[3] - BOX[1]) * 1.0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "// Generated by tools/trace_logo.py from the KRIKO wordmark reference.\n"
        "// Do not hand-edit: re-run the tracer instead.\n"
        f"export const LOGO_WIDTH = {width:g};\n"
        f"export const LOGO_HEIGHT = {height:g};\n"
        f"export const LOGO_PATHS = '{path}';\n",
        encoding="utf-8",
    )
    print(f"loops={len(loops)} points={total_points} path_chars={len(path)} -> {OUT}")


if __name__ == "__main__":
    main()
