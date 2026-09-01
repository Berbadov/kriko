"""Write the `packs.json` an installed Kriko checks for updates against.

Run over the built `.kpack` files, with the base URL their assets will live at:

    python packaging/publish_index.py --base-url \
        https://github.com/Berbadov/kriko/releases/download/v0.2.0 \
        --out release/packs.json release/*.kpack

Every field is read out of the pack file itself — the version, the name and the
`content_digest` are what the builder wrote, so an index cannot drift from the
artifact it describes by anyone forgetting to update a number by hand.

The `sha256` is over the file's bytes and is computed here, because it is the
only thing that can tell a downloader its copy arrived intact; `content_digest`
is over the pack's rows and is what decides whether the download is worth
making at all. See `kriko/pack/updates.py`.
"""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def describe(path: Path, base_url: str) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM packs").fetchall()
    finally:
        conn.close()
    if len(rows) != 1:
        raise SystemExit(f"{path.name} declares {len(rows)} packs; expected exactly one")
    pack = rows[0]
    return {
        "pack_id": pack["pack_id"],
        "name": pack["name"],
        "version": pack["version"],
        "url": f"{base_url.rstrip('/')}/{path.name}",
        "content_digest": pack["content_digest"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
        "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packs", nargs="+", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    index = {
        "packs": sorted(
            (describe(p, args.base_url) for p in args.packs),
            key=lambda row: row["pack_id"],
        )
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    for row in index["packs"]:
        print(f"{row['pack_id']} {row['version']} {row['size']} bytes -> {row['url']}")


if __name__ == "__main__":
    main()
