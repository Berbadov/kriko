"""Pack the frozen engine as the release asset an installed Kriko updates itself from.

    python packaging/make_engine_zip.py --engine dist/kriko-engine \
        --out kriko-ui/builds

writes two files into `--out`:

    kriko-engine-<version>-win64.zip   engine.json, kriko-sidecar.exe, _internal/
    engine.json                        what an installed Kriko reads before it downloads

An installed copy replaces its engine by unpacking this zip into a folder of
its own and starting it (`src/app/engineupdate.py`), where an installer would lay
files over the old ones. The zip is the whole engine, nothing else: the desktop
app, the window and OpenSERP are not in it and an engine update never touches
them.

`min_shell` is the oldest desktop app this engine update is offered to. It
defaults to the release's own version, so every release is installed whole: an
engine-only update leaves the reader's window as it was, and a release that
changed the interface then looks like an update that did nothing (0.3.3 shipped
that way, with the floor left at 0.3.2). A release that changed nothing the
window draws or starts may open the engine-only path with
`--engine-only-from <oldest desktop app>`; saying so is the only way to get it.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = "kriko-sidecar.exe"
_VERSION = re.compile(r"^[0-9][0-9A-Za-z.\-]*$")


def tree_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def pack(engine: Path, out: Path, version: str, *, min_shell: str = "") -> Path:
    """Write the zip and `engine.json`; return the zip's path.

    `min_shell` is the oldest desktop app offered the engine alone; left empty it
    is `version` itself, which sends every installed app to the installer.
    """
    if not _VERSION.match(version):
        raise SystemExit(f"{version!r} is not a version")
    min_shell = min_shell or version
    if not _VERSION.match(min_shell):
        raise SystemExit(f"{min_shell!r} is not a version")
    program = engine / SIDECAR
    internal = engine / "_internal"
    if not program.is_file() or not internal.is_dir():
        raise SystemExit(f"{engine} is not a frozen engine folder: it needs {SIDECAR} and _internal/")
    manifest = {"version": version, "min_shell": min_shell, "asset": f"kriko-engine-{version}-win64.zip"}
    out.mkdir(parents=True, exist_ok=True)
    target = out / manifest["asset"]
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("engine.json", json.dumps(manifest, indent=2) + "\n")
        zf.write(program, SIDECAR)
        for path in sorted(internal.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(engine).as_posix())
    (out / "engine.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path, help="the frozen folder (dist/kriko-engine)")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--version", default="", help="checked against pyproject.toml; defaults to it")
    parser.add_argument(
        "--engine-only-from",
        default="",
        metavar="VERSION",
        help="the oldest desktop app that may take this engine without the installer; "
        "default: this release, so the installer is always the way in",
    )
    args = parser.parse_args(argv)
    tree = tree_version()
    version = (args.version or tree).removeprefix("v")
    if version != tree:
        raise SystemExit(f"asked for {version} and this tree is {tree}: the zip's name and contents come from the tree")
    made = pack(args.engine, args.out, version, min_shell=args.engine_only_from)
    print(f"{made}  {made.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
