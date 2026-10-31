"""Pack every published catalog and its index into one archive.

    python packaging/make_packs_bundle.py --out release/packs-0.3.9.zip \
        release/packs.json release/*.kpack

The app's update channel is the per-pack files: `packs.json` names each one,
and `app/packsource.py` downloads and verifies them one at a time, so a weekly
check fetches only the catalogs whose `content_digest` moved. This archive is
the human/offline copy of the same set — one attachment to download, one folder
to hand to somebody — and never a replacement for the files the app reads.

It refuses to build a bundle that would lie: every `.kpack` handed to it must
be named by the index, and every file the index names must be handed to it.

Entry timestamps are the newest input's, so the same inputs produce the same
bytes and a re-run does not change the asset's hash for no reason.
"""

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path


def _listed(index: Path) -> set[str]:
    data = json.loads(index.read_text(encoding="utf-8"))
    rows = data.get("packs", []) if isinstance(data, dict) else data
    return {str(row["url"]).rsplit("/", 1)[-1] for row in rows if row.get("url")}


def build(index: Path, packs: list[Path], out: Path) -> dict:
    named = _listed(index)
    given = {path.name for path in packs}
    if not named:
        raise SystemExit(f"{index} names no catalogs")
    if named != given:
        missing = ", ".join(sorted(named - given)) or "none"
        extra = ", ".join(sorted(given - named)) or "none"
        raise SystemExit(
            f"the index and the catalog files disagree: not given [{missing}], "
            f"not in the index [{extra}]"
        )
    newest = max(path.stat().st_mtime for path in packs + [index])
    stamp = datetime.fromtimestamp(newest).timetuple()[:6]
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(packs):
            info = zipfile.ZipInfo(f"packs/{path.name}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
        info = zipfile.ZipInfo("packs.json", date_time=stamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, index.read_bytes(), compresslevel=9)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return {
        "path": out,
        "files": len(packs) + 1,
        "size": out.stat().st_size,
        "sha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("index", type=Path, help="the published packs.json")
    parser.add_argument("packs", nargs="+", type=Path, help="the .kpack files it names")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.index, args.packs, args.out)
    except (OSError, ValueError, KeyError) as error:
        print(f"could not build the bundle: {error}", file=sys.stderr)
        return 1
    print(f"{result['path']}  {result['files']} files  {result['size']} bytes")
    print(f"sha256 {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
