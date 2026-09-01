"""Assemble the `latest.json` Tauri's updater polls.

Three OS runners each bundle their own updater artifact and its detached
`.sig`; nothing in `tauri build` knows about the other two. This script is the
join: it walks the downloaded artifacts, pairs each bundle with its signature,
and writes the one manifest an installed app reads.

Platform keys are Tauri's (`linux-x86_64`, `darwin-aarch64`, …). A missing
platform is not an error — a release built on two runners should still update
those two — but a bundle with no `.sig` beside it is, because the app would
download it and refuse it.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

#: Which bundle each platform's updater actually installs. Tauri emits an
#: AppImage on Linux, an app tarball on macOS and the NSIS installer on Windows.
SUFFIXES = {
    ".AppImage": ["linux-x86_64"],
    ".tar.gz": ["darwin-aarch64", "darwin-x86_64"],
    ".exe": ["windows-x86_64"],
}


def platforms_for(path: Path) -> list[str]:
    for suffix, platforms in SUFFIXES.items():
        if path.name.endswith(suffix):
            # macOS's updater tarball is the only .tar.gz Tauri produces, and
            # its architecture is not in the file name — so both Apple keys
            # point at it and the app picks the one it is.
            return platforms
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--version", required=True, help="without a leading v")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--notes", default="See the release notes.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    platforms: dict[str, dict] = {}
    copied: list[Path] = []
    for signature in sorted(args.artifacts.rglob("*.sig")):
        bundle = signature.with_suffix("")
        if not bundle.exists():
            raise SystemExit(f"{signature.name} has no bundle beside it")
        keys = platforms_for(bundle)
        if not keys:
            continue
        entry = {
            "signature": signature.read_text(encoding="utf-8").strip(),
            "url": f"{args.base_url.rstrip('/')}/{bundle.name}",
        }
        for key in keys:
            platforms[key] = entry
        copied.append(bundle)
        copied.append(signature)

    if not platforms:
        raise SystemExit(
            "no updater artifacts were produced — the build ran without "
            "TAURI_SIGNING_PRIVATE_KEY, so there is nothing to publish"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "version": args.version,
                "notes": args.notes,
                "pub_date": datetime.now(UTC).isoformat(timespec="seconds"),
                "platforms": dict(sorted(platforms.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for path in copied:
        target = args.out.parent / path.name
        if target != path:
            target.write_bytes(path.read_bytes())
    print(f"{args.out} covers {', '.join(sorted(platforms))}")


if __name__ == "__main__":
    main()
