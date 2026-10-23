"""Prepare the stable shared-access pepper for a desktop sidecar build.

If KRIKO_SHARE_PEPPER is set, it is written to the gitignored source module
PyInstaller freezes. Otherwise a previously generated local module is kept.
The value is never printed. Supply the same 32-byte hex value to every build
that must accept access codes across platforms.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "app" / "sharekeys_pepper.py"
TEMPLATE = '''"""Build's shared-access pepper. Generated; do not commit."""

PEPPER = {value!r}
'''
VALID = re.compile(r"^[0-9a-fA-F]{64}$")


def existing_value() -> str:
    if not TARGET.is_file():
        return ""
    source = TARGET.read_text(encoding="utf-8")
    match = re.search(r"^PEPPER\s*=\s*(['\"])([^'\"]*)\1\s*$", source, re.MULTILINE)
    return match.group(2) if match else ""


def main() -> int:
    value = os.environ.get("KRIKO_SHARE_PEPPER", "")
    if value:
        if not VALID.fullmatch(value):
            print("KRIKO_SHARE_PEPPER must be exactly 64 hexadecimal characters (32 bytes).",
                  file=sys.stderr)
            return 2
        current = existing_value()
        if TARGET.exists() and current != value:
            print(
                "KRIKO_SHARE_PEPPER differs from the existing local pepper. "
                "Choose the intended stable value explicitly; this build left "
                "the local pepper untouched.",
                file=sys.stderr,
            )
            return 2
        if current == value:
            print("Using the configured app-bound shared-access pepper for this build.")
            return 0
        TARGET.write_text(TEMPLATE.format(value=value), encoding="utf-8")
        print("Configured the app-bound shared-access pepper for this build.")
        return 0

    if VALID.fullmatch(existing_value()):
        print("Using the existing app-bound shared-access pepper for this build.")
        return 0

    print(
        "Shared access cannot be packaged without a stable pepper. Set the "
        "KRIKO_SHARE_PEPPER build secret/environment variable (64 hex characters), "
        "or generate a local pepper with tools/make_share_pepper.py.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
