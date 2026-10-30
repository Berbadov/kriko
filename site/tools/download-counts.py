"""Read aggregate GitHub release downloads without adding website tracking.

    python site/tools/download-counts.py --save /tmp/kriko-downloads.json
    python site/tools/download-counts.py --previous /tmp/kriko-downloads.json

Counts are asset downloads, not people, successful installs or website clicks.
GitHub CLI must be available. No credentials or visitor data are saved.
"""

import argparse
import datetime
import json
import re
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, help="write a snapshot to this path")
    parser.add_argument("--previous", type=Path, help="compare with an earlier snapshot")
    args = parser.parse_args()
    release_lines = subprocess.check_output([
        "gh", "api", "repos/Berbadov/kriko/releases?per_page=100", "--paginate", "--jq", ".[] | @json",
    ], text=True)
    releases = [json.loads(line) for line in release_lines.splitlines() if line.strip()]
    assets = [
        {"id": asset["id"], "release": release["tag_name"], "name": asset["name"],
         "downloads": asset["download_count"]}
        for release in releases
        if not release["draft"] and not release["prerelease"]
        for asset in release["assets"]
        if re.fullmatch(r"kriko-\d+\.\d+\.\d+-(?:x86_64-setup\.exe|win64-portable\.zip)", asset["name"])
    ]
    snapshot = {"captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "metric": "GitHub desktop release asset downloads, not installs or unique users",
                "total_downloads": sum(asset["downloads"] for asset in assets), "assets": assets}
    if args.previous:
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
        before = {asset["id"]: asset["downloads"] for asset in previous["assets"]}
        removed = set(before) - {asset["id"] for asset in assets}
        snapshot["since"] = previous["captured_at"]
        snapshot["additional_downloads"] = sum(asset["downloads"] - before.get(asset["id"], 0) for asset in assets)
        snapshot["removed_asset_ids"] = sorted(removed)
        if removed:
            snapshot["comparison_note"] = "Some earlier assets are missing. Delta covers available assets only."
    output = json.dumps(snapshot, indent=2) + "\n"
    if args.save:
        args.save.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
