"""Build every first-party pack into `dist/`, for the installer to carry.

    python packaging/build_packs.py

One step in two build paths — `.github/workflows/desktop.yml` and
`packaging/build_desktop.ps1` — and a Python file rather than a line in each of
them, because a step written twice in two languages is a step that will
eventually differ in one of them. `packaging/kriko-sidecar.spec` refuses to
freeze without the artifacts this writes, the same way it already refuses
without a built frontend.

**Which packs get built is discovered, never listed.** Anything under `packs/`
with a `pack.toml` is a pack, so a third first-party pack ships by existing and
nobody has to remember to add it here — the same rule the scalability principle
in CLAUDE.md applies to catalog data, applied to the build. A hand-written list
in this file would be the next `SIBLING_CODE_FAMILIES`.

The output name comes from the *directory*, not from the pack's declared id:
`app/bundledpacks.py` reads every carried artifact's identity out of the
artifact itself, so a file name is a file name here and nothing downstream
trusts it.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "packs"
OUT = ROOT / "dist"


def pack_dirs() -> list[Path]:
    """Every pack directory in the repository, in a stable order."""
    return sorted(
        path.parent for path in PACKS.glob("*/pack.toml") if path.is_file()
    )


def main() -> int:
    found = pack_dirs()
    if not found:
        print("no pack directories under packs/", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for root in found:
        target = OUT / f"{root.name}.kpack"
        # Through the CLI rather than by importing the builder: this is the
        # command a reader would run, and a build step that exercises a
        # different entry point than the documented one has tested the wrong
        # thing. `-m app.cli` so it works from a checkout with no console
        # script installed.
        done = subprocess.run(
            [sys.executable, "-m", "app.cli", "build",
             str(root.relative_to(ROOT)), "--out", str(target)],
            cwd=ROOT,
        )
        if done.returncode != 0:
            print(f"could not build {root.name}", file=sys.stderr)
            return done.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
