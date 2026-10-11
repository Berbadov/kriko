#!/usr/bin/env bash
# Freeze the sidecar and prove the frozen binary works — the same two steps CI
# runs before "bundle the desktop app", available locally
# because the failures they catch (a missing hidden import, an undeclared data
# file) do not exist in a source checkout and so cannot be caught by pytest.
#
#   packaging/freeze.sh            # build + smoke
# Needs no Rust toolchain, and stops one step short of an installer. For the
# whole bundle on a Windows box, see `kriko-gpui/package.ps1`.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-.venv/bin/python}

# PyInstaller's scratch is rebuilt on every freeze, so it stays out of the
# checkout. A build/ beside the spec was a second copy of everything.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$PYTHON" -m PyInstaller --noconfirm --distpath dist --workpath "$WORK" \
    packaging/kriko-sidecar.spec

"$PYTHON" packaging/smoke_sidecar.py dist/kriko-sidecar
ls -lh dist/kriko-sidecar
