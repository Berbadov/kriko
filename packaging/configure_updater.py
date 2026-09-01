"""Turn the app's self-update on, but only when it can actually be trusted.

Tauri's updater verifies every downloaded bundle against a minisign public key
compiled into the app. That key is independent of Apple/EV code signing, which
is why auto-update can work on the unsigned installers Kriko ships — but it
means the private half has to exist somewhere, and it lives in a repository
secret rather than in this tree.

So the updater is *configuration*, applied at build time:

* with `TAURI_SIGNING_PUBLIC_KEY` set, the endpoint and the key go into
  `tauri.conf.json` and the bundlers emit updater artifacts;
* without it, both come back out, and the build produces plain installers.

The alternative — committing the updater config and requiring the secret —
means a fork, or this repo before anyone generates a key, fails to build at
all. And the worse alternative, building updater artifacts with a throwaway
key, ships an app that downloads its own updates and then rejects them.

    python packaging/configure_updater.py --repo owner/name
"""

import argparse
import json
import os
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "tauri" / "src-tauri" / "tauri.conf.json"

#: `latest`, not a tag: an installed app has to find the newest release without
#: being told which one that is. `{{target}}` and `{{arch}}` are Tauri's own
#: placeholders, but one manifest covers every platform, so they go unused.
ENDPOINT = "https://github.com/{repo}/releases/latest/download/latest.json"


def configure(config: dict, repo: str, pubkey: str, version: str = "") -> dict:
    plugins = dict(config.get("plugins") or {})
    bundle = dict(config.get("bundle") or {})
    if pubkey.strip():
        plugins["updater"] = {
            "endpoints": [ENDPOINT.format(repo=repo)],
            "pubkey": pubkey.strip(),
            # NSIS asks nothing on Windows; the app was already told yes.
            "windows": {"installMode": "passive"},
        }
        bundle["createUpdaterArtifacts"] = True
    else:
        plugins.pop("updater", None)
        bundle.pop("createUpdaterArtifacts", None)
    out = config | {"plugins": plugins, "bundle": bundle}
    if version:
        # The updater compares the running app's version against the manifest,
        # so a build made from tag v0.2.0 that still calls itself 0.1.0 would
        # offer itself its own update, forever.
        out["version"] = version.lstrip("v")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument(
        "--version", default="", help="stamp this version (a tag like v0.2.0 is fine)"
    )
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    updated = configure(
        config,
        args.repo,
        os.environ.get("TAURI_SIGNING_PUBLIC_KEY", ""),
        args.version,
    )
    args.config.write_text(json.dumps(updated, indent=4) + "\n", encoding="utf-8")
    print(
        "updater enabled: " + updated["plugins"]["updater"]["endpoints"][0]
        if "updater" in updated["plugins"]
        else "updater disabled — TAURI_SIGNING_PUBLIC_KEY is not set, so this "
        "build ships plain installers"
    )


if __name__ == "__main__":
    main()
