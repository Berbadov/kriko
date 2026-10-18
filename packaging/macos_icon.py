"""Build the macOS iconset from the desktop app's checked ICO artwork.

The source icon is the same white K on the Kriko blue plate used by the
Windows executable. macOS's ``sips`` makes the additional sizes and
``iconutil`` wraps them in the native ICNS container.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from render_icon import ico_images

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "kriko-ui" / "src-tauri" / "icons" / "icon.ico"
ICONSET = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def build_iconset(iconset_dir: Path, output: Path, source: Path = SOURCE) -> None:
    """Write the iconset and its native ICNS file using Apple's tools."""
    if sys.platform != "darwin":
        raise RuntimeError("macOS icons are packaged with sips and iconutil on macOS")
    for tool in ("sips", "iconutil"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} is required to build the macOS app icon")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    iconset_dir.mkdir(parents=True, exist_ok=True)
    if any(iconset_dir.iterdir()):
        raise FileExistsError(f"iconset directory is not empty: {iconset_dir}")

    images = ico_images(source.read_bytes())
    master = images.get(256)
    if master is None:
        raise ValueError(f"{source} has no 256px PNG entry")
    width, height = struct.unpack(">II", master[16:24])
    if (width, height) != (256, 256):
        raise ValueError(f"the 256px ICO entry is {width}x{height}")

    master_path = iconset_dir / "source-256.png"
    master_path.write_bytes(master)
    for filename, size in ICONSET:
        destination = iconset_dir / filename
        exact = images.get(size)
        if exact is not None:
            destination.write_bytes(exact)
        else:
            subprocess.run(
                ["sips", "-z", str(size), str(size), str(master_path), "--out", str(destination)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
    master_path.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "--output", str(output)],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iconset_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        build_iconset(args.iconset_dir, args.output)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
