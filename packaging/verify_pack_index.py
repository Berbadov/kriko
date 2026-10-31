"""Check that a published pack index is one a reader's Kriko can install from.

    python packaging/verify_pack_index.py \
        https://github.com/Berbadov/kriko/releases/latest/download/packs.json

It does what the app does when a reader presses Find release catalogs: reads the
index, then downloads every catalog it names and checks the bytes against the
`sha256` the index promised, using the app's own `app.packsource`. A release that
is missing `packs.json`, or whose index names a file that is not there, fails
here with the address that failed, instead of in front of the first reader.

Run it against `.../releases/latest/download/packs.json` after publishing a
release, because that is the address every installed app asks. It exists because
0.3.5 published an index whose catalogs were never attached, and 0.3.6 and 0.3.7
published no index at all, so for two releases the website's step "install a
catalog" ended in an error. Exits 1 when anything is wrong.
"""

import argparse
import sys
import tempfile
from pathlib import Path

from app import packsource


def problems(index_url: str, *, allow_private: bool = False) -> list[str]:
    """Everything wrong with the index at `index_url`; empty when a reader can install from it."""
    try:
        candidates = packsource.fetch_index(index_url, allow_private=allow_private)
    except Exception as exc:  # noqa: BLE001 - any failure to read it is the finding
        return [f"{index_url} could not be read: {exc}"]
    if not candidates:
        return [f"{index_url} lists no catalogs"]
    found = []
    with tempfile.TemporaryDirectory() as scratch:
        for candidate in candidates:
            try:
                packsource.download(candidate, Path(scratch), allow_private=allow_private)
            except Exception as exc:  # noqa: BLE001 - the pack that failed is what to report
                found.append(f"{candidate.pack_id} {candidate.version}: {candidate.url} did not download: {exc}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("index_url")
    args = parser.parse_args()
    found = problems(args.index_url)
    for line in found:
        print(f"FAIL {line}", file=sys.stderr)
    if not found:
        print(f"ok: every catalog in {args.index_url} downloads and matches its sha256")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
